"""联备方案状态机：草案/生效/取消、占用语义、并发与幂等、依据冻结。"""
import threading

from src.config.database import Session
from src.models.entities import Job, Kit, KittingOccupancy, KittingPlan

from conftest import get_job, make_jobs, make_kit


def occupancy():
    with Session() as s:
        return sorted((o.plan_id, o.job_id) for o in s.query(KittingOccupancy).all())


def plan_state(plan_id):
    with Session() as s:
        p = s.get(KittingPlan, plan_id)
        return p.state


def setup_env(client, tokens):
    """三张作业 + 两个可全覆盖的已签核包。"""
    ids = make_jobs(client, tokens['analyst'], [
        ('YH-T-001', ['轴承', '润滑脂']),
        ('YH-T-002', ['密封圈']),
        ('YH-T-003', ['滤芯']),
    ])
    k1 = make_kit('轴封包', ['轴承', '润滑脂', '密封圈'])
    k2 = make_kit('滤芯包', ['滤芯'])
    return ids, [k1, k2]


def trial(client, header, job_ids, kit_ids=None, limit=6, name='联备测试方案'):
    r = client.post('/plans/trial', json={
        'name': name, 'job_ids': job_ids, 'kit_ids': kit_ids, 'carry_limit': limit}, headers=header)
    assert r.status_code == 200, r.text
    return r.json()


def test_trial_creates_draft_without_occupancy(client, tokens):
    ids, kits = setup_env(client, tokens)
    p = trial(client, tokens['analyst'], list(ids.values()), kits)
    assert p['state'] == 'draft'
    assert p['result']['covered'] == 3 and p['result']['total'] == 3
    assert p['result']['carried_count'] <= 6
    assert occupancy() == []                       # 草案不占用
    assert p['basis']['jobs'] and p['basis']['kits']  # 依据快照已记录
    assert p['fingerprint']


def test_confirm_occupies_and_same_key_retry_is_idempotent(client, tokens):
    ids, kits = setup_env(client, tokens)
    p = trial(client, tokens['analyst'], list(ids.values()), kits)
    key = 'confirm-key-0001'
    r1 = client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': key}, headers=tokens['analyst'])
    assert r1.status_code == 200 and r1.json()['state'] == 'active'
    occ1 = occupancy()
    assert len(occ1) == 3 and all(pid == p['id'] for pid, _ in occ1)
    # 同键重试（网络重试/双击）：幂等成功，不重复占用
    r2 = client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': key}, headers=tokens['analyst'])
    assert r2.status_code == 200 and r2.json()['state'] == 'active'
    assert occupancy() == occ1
    assert r2.json()['activated_at'] == r1.json()['activated_at']
    # 不同键重复确认：拒绝
    r3 = client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': 'another-key-2'}, headers=tokens['analyst'])
    assert r3.status_code == 409


def test_same_job_not_occupied_by_two_plans(client, tokens):
    ids, kits = setup_env(client, tokens)
    pa = trial(client, tokens['analyst'], list(ids.values()), kits, name='方案A')
    pb = trial(client, tokens['analyst'], [ids['YH-T-001']], kits, name='方案B')
    ra = client.post(f"/plans/{pa['id']}/confirm", json={'idempotency_key': 'key-a-0001'}, headers=tokens['analyst'])
    assert ra.status_code == 200
    rb = client.post(f"/plans/{pb['id']}/confirm", json={'idempotency_key': 'key-b-0001'}, headers=tokens['analyst'])
    assert rb.status_code == 409 and '占用' in rb.json()['detail']
    assert plan_state(pb['id']) == 'draft'         # 冲突后仍是草案，可调整后再试
    job_ids = [j for _, j in occupancy()]
    assert len(job_ids) == len(set(job_ids))       # 不超占


def test_concurrent_confirm_no_overbook(client, tokens):
    ids, kits = setup_env(client, tokens)
    pa = trial(client, tokens['analyst'], list(ids.values()), kits, name='并发A')
    pb = trial(client, tokens['analyst'], list(ids.values()), kits, name='并发B')
    barrier = threading.Barrier(2)
    results = {}

    def do(pid, key, tag):
        barrier.wait()
        r = client.post(f'/plans/{pid}/confirm', json={'idempotency_key': key}, headers=tokens['analyst'])
        results[tag] = r.status_code

    ts = [threading.Thread(target=do, args=(pa['id'], 'race-a-001', 'a')),
          threading.Thread(target=do, args=(pb['id'], 'race-b-001', 'b'))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results.values()) == [200, 409]  # 恰好一个胜出
    job_ids = [j for _, j in occupancy()]
    assert len(job_ids) == len(set(job_ids)) == 3  # 不超占
    states = sorted([plan_state(pa['id']), plan_state(pb['id'])])
    assert states == ['active', 'draft']


def test_concurrent_same_plan_same_key_all_succeed_once(client, tokens):
    ids, kits = setup_env(client, tokens)
    p = trial(client, tokens['analyst'], list(ids.values()), kits)
    barrier = threading.Barrier(5)
    results = []

    def do():
        barrier.wait()
        r = client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': 'same-key-999'}, headers=tokens['analyst'])
        results.append(r.status_code)

    ts = [threading.Thread(target=do) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results == [200] * 5                    # 重试/并发同键全部幂等成功
    assert len(occupancy()) == 3                   # 占用只写了一遍


def test_cancel_releases_and_repeated_cancel_never_touches_others(client, tokens):
    ids, kits = setup_env(client, tokens)
    pa = trial(client, tokens['analyst'], list(ids.values()), kits, name='先占')
    client.post(f"/plans/{pa['id']}/confirm", json={'idempotency_key': 'key-pa-0001'}, headers=tokens['analyst'])
    assert len(occupancy()) == 3
    r = client.post(f"/plans/{pa['id']}/cancel", json={'idempotency_key': 'cancel-pa-1'}, headers=tokens['analyst'])
    assert r.status_code == 200 and r.json()['state'] == 'cancelled'
    assert occupancy() == []                       # 取消释放占用
    # 另一方案现在可以占用同一批作业
    pb = trial(client, tokens['analyst'], list(ids.values()), kits, name='后占')
    rb = client.post(f"/plans/{pb['id']}/confirm", json={'idempotency_key': 'key-pb-0001'}, headers=tokens['analyst'])
    assert rb.status_code == 200
    occ_after = occupancy()
    assert len(occ_after) == 3 and all(pid == pb['id'] for pid, _ in occ_after)
    # 重复取消已取消的方案（同键重试与不同键）：都不误释放方案B的占用
    for key in ('cancel-pa-1', 'cancel-pa-2'):
        r = client.post(f"/plans/{pa['id']}/cancel", json={'idempotency_key': key}, headers=tokens['analyst'])
        assert r.status_code == 200 and r.json()['state'] == 'cancelled'
        assert occupancy() == occ_after
    assert plan_state(pb['id']) == 'active'


def test_stale_after_job_revision_rejected_then_retrial(client, tokens):
    ids, kits = setup_env(client, tokens)
    p = trial(client, tokens['analyst'], list(ids.values()), kits)
    # 试算后修订作业
    r = client.put(f"/jobs/{ids['YH-T-001']}", json={
        'code': 'YH-T-001', 'equipment': '泵组', 'parts': ['轴承', '垫片'], 'note': '修订'}, headers=tokens['analyst'])
    assert r.status_code == 200
    rc = client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': 'stale-key-1'}, headers=tokens['analyst'])
    assert rc.status_code == 409 and '重新试算' in rc.json()['detail']
    assert plan_state(p['id']) == 'draft'
    assert occupancy() == []
    # 重新试算后基于新依据可生效
    p2 = trial(client, tokens['analyst'], list(ids.values()), kits)
    r2 = client.post(f"/plans/{p2['id']}/confirm", json={'idempotency_key': 'fresh-key-1'}, headers=tokens['analyst'])
    assert r2.status_code == 200
    assert get_job(ids['YH-T-001'])['revision'] == 2


def test_stale_after_kit_revoked_rejected(client, tokens):
    ids, kits = setup_env(client, tokens)
    p = trial(client, tokens['analyst'], list(ids.values()), kits)
    r = client.post(f"/kits/{kits[0]}/revoke", headers=tokens['admin'])
    assert r.status_code == 200 and r.json()['status'] == 'revoked'
    rc = client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': 'stale-kit-1'}, headers=tokens['analyst'])
    assert rc.status_code == 409 and '重新试算' in rc.json()['detail']


def test_frozen_basis_after_activation(client, tokens):
    ids, kits = setup_env(client, tokens)
    p = trial(client, tokens['analyst'], list(ids.values()), kits)
    client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': 'freeze-key1'}, headers=tokens['analyst'])
    d1 = client.get(f"/plans/{p['id']}", headers=tokens['viewer']).json()
    assert d1['state'] == 'active' and d1['activated_at']
    basis_snapshot = d1['basis']
    # 生效后取消方案再修订作业：已冻结的依据不变
    client.post(f"/plans/{p['id']}/cancel", json={'idempotency_key': 'freeze-key2'}, headers=tokens['analyst'])
    client.put(f"/jobs/{ids['YH-T-001']}", json={
        'code': 'YH-T-001', 'equipment': '泵组', 'parts': ['轴承'], 'note': ''}, headers=tokens['analyst'])
    d2 = client.get(f"/plans/{p['id']}", headers=tokens['viewer']).json()
    assert d2['basis'] == basis_snapshot


def test_occupied_job_cannot_be_revised_until_cancel(client, tokens):
    ids, kits = setup_env(client, tokens)
    p = trial(client, tokens['analyst'], list(ids.values()), kits)
    client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': 'lock-key-01'}, headers=tokens['analyst'])
    r = client.put(f"/jobs/{ids['YH-T-001']}", json={
        'code': 'YH-T-001', 'equipment': '泵组', 'parts': ['轴承'], 'note': ''}, headers=tokens['analyst'])
    assert r.status_code == 409 and '占用' in r.json()['detail']
    assert get_job(ids['YH-T-001'])['revision'] == 1   # 未生效的修订不留痕
    client.post(f"/plans/{p['id']}/cancel", json={'idempotency_key': 'lock-key-02'}, headers=tokens['analyst'])
    r2 = client.put(f"/jobs/{ids['YH-T-001']}", json={
        'code': 'YH-T-001', 'equipment': '泵组', 'parts': ['轴承'], 'note': ''}, headers=tokens['analyst'])
    assert r2.status_code == 200
    assert get_job(ids['YH-T-001'])['revision'] == 2


def test_kit_in_use_cannot_be_revoked(client, tokens):
    ids, kits = setup_env(client, tokens)
    p = trial(client, tokens['analyst'], list(ids.values()), kits)
    client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': 'kit-use-01'}, headers=tokens['analyst'])
    r = client.post(f"/kits/{kits[0]}/revoke", headers=tokens['admin'])
    assert r.status_code == 409
    client.post(f"/plans/{p['id']}/cancel", json={'idempotency_key': 'kit-use-02'}, headers=tokens['analyst'])
    r2 = client.post(f"/kits/{kits[0]}/revoke", headers=tokens['admin'])
    assert r2.status_code == 200


def test_revision_vs_confirm_race_keeps_consistent_version(client, tokens):
    """修订与确认竞争：每轮终态必须一致——要么确认生效且修订被拒，
    要么修订成功且确认因依据过期被拒；绝不出现基于旧版本生效而作业已改。"""
    for round_no in range(5):
        ids = make_jobs(client, tokens['analyst'], [(f'YH-R-{round_no}-1', ['轴承', '润滑脂'])])
        kit_id = make_kit(f'竞争包{round_no}', ['轴承', '润滑脂'])
        p = trial(client, tokens['analyst'], list(ids.values()), [kit_id])
        jid = list(ids.values())[0]
        before = get_job(jid)['revision']
        barrier = threading.Barrier(2)
        out = {}

        def do_confirm():
            barrier.wait()
            out['confirm'] = client.post(f"/plans/{p['id']}/confirm",
                                         json={'idempotency_key': f'race-key-{round_no}'}, headers=tokens['analyst']).status_code

        def do_revise():
            barrier.wait()
            out['revise'] = client.put(f'/jobs/{jid}', json={
                'code': f'YH-R-{round_no}-1', 'equipment': '泵组', 'parts': ['轴承', '垫片'], 'note': ''},
                headers=tokens['analyst']).status_code

        t1, t2 = threading.Thread(target=do_confirm), threading.Thread(target=do_revise)
        t1.start(); t2.start(); t1.join(); t2.join()
        state, rev = plan_state(p['id']), get_job(jid)['revision']
        confirm_wins = (out['confirm'] == 200 and out['revise'] == 409
                        and state == 'active' and rev == before)
        revise_wins = (out['confirm'] == 409 and out['revise'] == 200
                       and state == 'draft' and rev == before + 1)
        assert confirm_wins or revise_wins, (round_no, out, state, rev)
        # 清理占用，下一轮互不影响
        client.post(f"/plans/{p['id']}/cancel", json={'idempotency_key': f'race-clean-{round_no}'}, headers=tokens['analyst'])


def test_viewer_readonly_and_unapproved_kit_rejected(client, tokens):
    ids, kits = setup_env(client, tokens)
    draft_kit = make_kit('未签核包', ['垫片'], status='draft')
    r = client.post('/plans/trial', json={'name': '权限测试', 'job_ids': list(ids.values()),
                                          'kit_ids': kits, 'carry_limit': 6}, headers=tokens['viewer'])
    assert r.status_code == 403
    r2 = client.post('/plans/trial', json={'name': '未签核测试', 'job_ids': list(ids.values()),
                                           'kit_ids': [draft_kit], 'carry_limit': 6}, headers=tokens['analyst'])
    assert r2.status_code == 409 and '签核' in r2.json()['detail']
    p = trial(client, tokens['analyst'], list(ids.values()), kits)
    assert client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': 'viewer-001'},
                       headers=tokens['viewer']).status_code == 403
    assert client.post(f"/plans/{p['id']}/cancel", json={'idempotency_key': 'viewer-002'},
                       headers=tokens['viewer']).status_code == 403
    # viewer 可以查看方案与逐单对账
    assert client.get('/plans', headers=tokens['viewer']).status_code == 200
    assert client.get(f"/plans/{p['id']}", headers=tokens['viewer']).status_code == 200


def test_cancelled_plan_cannot_confirm_and_audit_trail(client, tokens):
    ids, kits = setup_env(client, tokens)
    p = trial(client, tokens['analyst'], list(ids.values()), kits)
    client.post(f"/plans/{p['id']}/cancel", json={'idempotency_key': 'cancel-first'}, headers=tokens['analyst'])
    r = client.post(f"/plans/{p['id']}/confirm", json={'idempotency_key': 'confirm-late'}, headers=tokens['analyst'])
    assert r.status_code == 409
    audits = client.get('/audits', headers=tokens['admin']).json()
    actions = [a['action'] for a in audits]
    assert any('试算联备方案' in a for a in actions)
    assert any('取消联备方案' in a for a in actions)
