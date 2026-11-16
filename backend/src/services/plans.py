"""联备方案生命周期：草案 -> 生效 -> 取消。

并发与一致性口径：
- 草案不占用作业；确认生效时才写入占用，取消时按 plan_id 精确释放。
- 占用表对 job_id 唯一约束：同一作业不会被多个生效方案占用，并发确认由数据库兜底不超占。
- 确认/取消都是条件更新（WHERE state=...）+ 影响行数判断，重试与并发下幂等，不重复占用、不误释放。
- 确认时先占位写把事务提升为写事务（SQLite 下避免读写升级死锁），再 SELECT ... FOR UPDATE
  锁定依据行并比对 revision/签核状态：试算之后作业修订或来源包变化即拒绝生效；
  修订与确认竞争时由行锁序列化，只保留一个一致版本。
- 生效后 basis/result 不再变化，即冻结依据。
"""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError, OperationalError

from src.models.entities import Job, Kit, KittingOccupancy, KittingPlan, KittingPlanKit
from src.services.business import audit
from src.services.kitting import plan_kitting


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint_of(jobs, kits, carry_limit):
    basis = {
        'carry_limit': carry_limit,
        'jobs': [{'id': j.id, 'code': j.code, 'parts': sorted(j.parts), 'revision': j.revision}
                 for j in sorted(jobs, key=lambda x: x.id)],
        'kits': [{'id': k.id, 'name': k.name, 'parts': sorted(k.parts), 'status': k.status, 'revision': k.revision}
                 for k in sorted(kits, key=lambda x: x.id)],
    }
    fp = hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return basis, fp


def get_plan(s, plan_id):
    plan = s.get(KittingPlan, plan_id)
    if not plan:
        raise HTTPException(404, '联备方案不存在')
    return plan


def trial(s, user, name, job_ids, kit_ids, carry_limit):
    jobs = s.query(Job).filter(Job.id.in_(job_ids)).order_by(Job.id).all()
    missing = sorted(set(job_ids) - {j.id for j in jobs})
    if missing:
        raise HTTPException(404, '作业不存在: ' + ','.join(map(str, missing)))
    if kit_ids:
        kits = s.query(Kit).filter(Kit.id.in_(kit_ids)).order_by(Kit.id).all()
        missed = sorted(set(kit_ids) - {k.id for k in kits})
        if missed:
            raise HTTPException(404, '备件包不存在: ' + ','.join(map(str, missed)))
    else:
        kits = s.query(Kit).filter(Kit.status == 'approved').order_by(Kit.id).all()
    not_approved = [k.name for k in kits if k.status != 'approved']
    if not_approved:
        raise HTTPException(409, '仅已签核备件包可参与联合备料: ' + '、'.join(not_approved))
    if not kits:
        raise HTTPException(409, '没有可用的已签核备件包，请先起草并签核')
    basis, fp = fingerprint_of(jobs, kits, carry_limit)
    result = plan_kitting(
        [{'id': j.id, 'code': j.code, 'parts': j.parts} for j in jobs],
        [{'id': k.id, 'name': k.name, 'parts': k.parts} for k in kits],
        carry_limit)
    plan = KittingPlan(name=name, state='draft', carry_limit=carry_limit, basis=basis,
                       fingerprint=fp, result=result, created_by=user.email, created_at=now())
    s.add(plan)
    s.commit()
    audit(s, user, f'试算联备方案 {plan.id}（覆盖 {result["covered"]}/{result["total"]}，闲置 {result["idle_total"]}）')
    return plan


def _check_basis_fresh(s, plan):
    """锁定并比对冻结依据：FOR UPDATE 行锁（MySQL）或写事务序列化（SQLite）保证
    校验与生效之间依据不会被并发修订改变。返回失效原因列表。"""
    stale = []
    job_ids = [x['id'] for x in plan.basis['jobs']]
    current = {j.id: j for j in s.query(Job).filter(Job.id.in_(job_ids)).with_for_update()}
    for jb in plan.basis['jobs']:
        cur = current.get(jb['id'])
        if not cur or cur.revision != jb['revision']:
            stale.append(f"作业 {jb['code']} 已修订")
    kit_ids = [x['id'] for x in plan.basis['kits']]
    current = {k.id: k for k in s.query(Kit).filter(Kit.id.in_(kit_ids)).with_for_update()}
    for kb in plan.basis['kits']:
        cur = current.get(kb['id'])
        if not cur or cur.revision != kb['revision'] or cur.status != 'approved':
            stale.append(f"备件包 {kb['name']} 已变化或取消签核")
    return stale


def confirm(s, user, plan_id, key):
    plan = get_plan(s, plan_id)
    if plan.state == 'active':
        if key and plan.confirm_key == key:
            return plan  # 同键重试：幂等返回，不重复占用
        raise HTTPException(409, '方案已生效，不可重复确认')
    if plan.state == 'cancelled':
        raise HTTPException(409, '方案已取消，请重新试算')

    def won_by_same_key():
        fresh = get_plan(s, plan_id)
        return fresh if fresh.state == 'active' and key and fresh.confirm_key == key else None

    try:
        # 首语句即写（占位登记确认键），把事务提升为写事务，避免读写升级死锁；
        # 后续任何校验失败都会回滚该占位。
        s.execute(update(KittingPlan).where(KittingPlan.id == plan_id, KittingPlan.state == 'draft')
                  .values(confirm_key=key))
        stale = _check_basis_fresh(s, plan)
        if stale:
            s.rollback()
            raise HTTPException(409, '试算依据已变化，拒绝生效，请重新试算：' + '；'.join(stale))
        job_ids = [a['job_id'] for a in plan.result['allocations']]
        held = {}
        if job_ids:
            held = {o.job_id: o.plan_id for o in
                    s.query(KittingOccupancy).filter(KittingOccupancy.job_id.in_(job_ids)).all()}
        if held:
            s.rollback()
            won = won_by_same_key()
            if won:
                return won  # 本方案的并发同键请求已生效
            clash = [a['code'] for a in plan.result['allocations'] if a['job_id'] in held]
            raise HTTPException(409, '作业已被其他生效方案占用：' + '、'.join(clash))
        r = s.execute(update(KittingPlan)
                      .where(KittingPlan.id == plan_id, KittingPlan.state == 'draft')
                      .values(state='active', activated_at=now(), version=KittingPlan.version + 1))
        if r.rowcount != 1:
            s.rollback()
            won = won_by_same_key()
            if won:
                return won
            raise HTTPException(409, '方案状态已变化，请刷新后重试')
        for a in plan.result['allocations']:
            s.add(KittingOccupancy(plan_id=plan_id, job_id=a['job_id'], created_at=now()))
        for kit_id in sorted({k for a in plan.result['allocations'] for k in a['kit_ids']}):
            s.add(KittingPlanKit(plan_id=plan_id, kit_id=kit_id))
        s.commit()
    except IntegrityError:
        # 占用唯一约束兜底：并发确认同一作业时只有一个方案胜出
        s.rollback()
        won = won_by_same_key()
        if won:
            return won
        raise HTTPException(409, '作业已被其他生效方案占用，请刷新后重试')
    except OperationalError:
        s.rollback()
        raise HTTPException(409, '并发确认冲突，请重试')
    plan = get_plan(s, plan_id)
    s.refresh(plan)  # Core UPDATE 不同步身份映射，提交后回读冻结后的真实状态
    audit(s, user, f'确认联备方案 {plan_id}（生效占用 {len(plan.result["allocations"])} 张作业）')
    return plan


def cancel(s, user, plan_id, key):
    plan = get_plan(s, plan_id)
    if plan.state == 'cancelled':
        return plan  # 重复取消：幂等返回，绝不再触碰占用表
    r = s.execute(update(KittingPlan)
                  .where(KittingPlan.id == plan_id, KittingPlan.state.in_(['draft', 'active']))
                  .values(state='cancelled', cancel_key=key, cancelled_at=now(),
                          version=KittingPlan.version + 1))
    if r.rowcount != 1:
        s.rollback()
        return get_plan(s, plan_id)  # 已被并发取消：幂等返回
    # 只按本方案 id 释放占用，绝不影响其他方案
    s.execute(delete(KittingOccupancy).where(KittingOccupancy.plan_id == plan_id))
    s.execute(delete(KittingPlanKit).where(KittingPlanKit.plan_id == plan_id))
    s.commit()
    audit(s, user, f'取消联备方案 {plan_id}')
    plan = get_plan(s, plan_id)
    s.refresh(plan)
    return plan
