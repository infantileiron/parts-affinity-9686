"""联合备料优化器：精确枚举的正确性、字典序目标、逐件对账与未覆盖原因。"""
import itertools

from src.services.kitting import plan_kitting


def greedy_per_order(jobs, kits, carry_limit):
    """逐单贪心基线：每单独立选最小闲置的包组合，按顺序登机；
    携带并集会超出件种上限时跳过该单。模拟班组按单挑包、缺乏全局协调。"""
    carried = set()
    covered = 0
    for j in jobs:
        need = set(j['parts'])
        best = None
        for r in range(1, len(kits) + 1):
            for combo in itertools.combinations(kits, r):
                union = set().union(*(set(k['parts']) for k in combo))
                if need <= union:
                    key = (len(union - need), sorted(union))
                    if best is None or key < best[0]:
                        best = (key, union)
            if best and best[0][0] == 0:
                break
        if best is None:
            continue
        if len(carried | best[1]) <= carry_limit:
            carried |= best[1]
            covered += 1
    return covered


def J(i, parts):
    return {'id': i, 'code': f'J{i:03}', 'parts': sorted(parts)}


def K(i, parts, name=None):
    return {'id': i, 'name': name or f'K{i}', 'parts': sorted(parts)}


def test_union_and_piecewise_reconcile():
    """每单可选多包、用件取并集、逐件对账：并集/覆盖/闲置逐件正确。"""
    kits = [K(1, ['轴承', '润滑脂']), K(2, ['密封圈']), K(3, ['滤芯'])]
    jobs = [J(1, ['轴承', '密封圈']), J(2, ['滤芯'])]
    r = plan_kitting(jobs, kits, 12)
    assert r['covered'] == 2 and r['total'] == 2
    a1 = next(a for a in r['allocations'] if a['job_id'] == 1)
    assert set(a1['kit_ids']) == {1, 2}                      # 多包并集
    assert set(a1['union_parts']) == {'轴承', '润滑脂', '密封圈'}
    assert a1['idle_parts'] == ['润滑脂']                     # 逐件闲置
    a2 = next(a for a in r['allocations'] if a['job_id'] == 2)
    assert a2['kit_ids'] == [3] and a2['idle_parts'] == []
    assert r['idle_total'] == 1


def test_lexicographic_objective_coverage_before_idle():
    """覆盖数优先于闲置：宁可选闲置更多但多覆盖一张作业的方案。"""
    kits = [K(1, ['轴承', '叶轮', '阀片']), K(2, ['密封圈']), K(3, ['滤芯']),
            K(4, ['清洗剂']), K(5, ['轴承', '密封圈', '滤芯', '清洗剂'])]
    jobs = [J(1, ['轴承']), J(2, ['密封圈']), J(3, ['滤芯']), J(4, ['清洗剂'])]
    r = plan_kitting(jobs, kits, 4)
    # 上限 4：用 K5 可四单全覆盖（J1 闲置 3 件）；用 K1 只能覆盖 2 单
    assert r['covered'] == 4
    assert r['carried_count'] <= 4
    assert r['idle_total'] == 3
    a1 = next(a for a in r['allocations'] if a['job_id'] == 1)
    assert a1['kit_ids'] == [5]


def test_min_idle_within_same_coverage():
    """覆盖数相同时选逐单闲置总数最小的分配。"""
    kits = [K(1, ['轴承', '润滑脂']), K(2, ['轴承'])]
    jobs = [J(1, ['轴承'])]
    r = plan_kitting(jobs, kits, 12)
    assert r['covered'] == 1 and r['idle_total'] == 0
    assert r['allocations'][0]['kit_ids'] == [2]


def test_carry_limit_respected_and_uncovered_reasons():
    """携带件种上限是硬约束；未覆盖给出分类原因。"""
    kits = [K(1, ['轴承', '润滑脂']), K(2, ['密封圈', '垫片']), K(3, ['滤芯', '清洗剂'])]
    jobs = [J(1, ['轴承']), J(2, ['密封圈']), J(3, ['滤芯']), J(4, ['传感器'])]
    r = plan_kitting(jobs, kits, 2)
    assert r['carried_count'] <= 2
    assert r['covered'] == 1                      # 上限 2 只能完整覆盖一单
    assert len(r['uncovered']) == 3
    uncovered = {u['job_id']: u for u in r['uncovered']}
    covered_id = r['allocations'][0]['job_id']
    assert set(uncovered) == {1, 2, 3, 4} - {covered_id}
    # 传感器不在任何已签核包中
    assert uncovered[4]['missing'][0]['reason'] == 'no_approved_kit'
    # 其余未覆盖单：有包含的包但受上限约束未携带
    for jid in ({1, 2, 3} - {covered_id}):
        assert uncovered[jid]['missing'][0]['reason'] == 'over_carry_limit'


def test_deterministic_same_input_same_output():
    kits = [K(1, ['轴承', '润滑脂']), K(2, ['密封圈']), K(3, ['垫片', '滤芯'])]
    jobs = [J(i, p) for i, p in enumerate([['轴承'], ['密封圈', '垫片'], ['滤芯']], 1)]
    assert plan_kitting(jobs, kits, 5) == plan_kitting(jobs, kits, 5)


def test_joint_beats_per_order_greedy():
    """联合优化严格优于逐单贪心：同一上限下覆盖更多作业。"""
    kits = [K(1, ['轴承', '叶轮', '阀片']), K(2, ['密封圈']), K(3, ['滤芯']),
            K(4, ['清洗剂']), K(5, ['轴承', '密封圈', '滤芯', '清洗剂'])]
    jobs = [J(1, ['轴承']), J(2, ['密封圈']), J(3, ['滤芯']), J(4, ['清洗剂'])]
    joint = plan_kitting(jobs, kits, 4)
    greedy = greedy_per_order(jobs, kits, 4)
    assert joint['covered'] == 4
    assert greedy == 2                            # 贪心先为 J1 挑了闲置最小的小包，挤爆上限
    assert joint['covered'] > greedy
    assert joint['carried_count'] <= 4


def test_joint_never_worse_than_greedy_randomized():
    """随机场景：联合覆盖数始终不低于逐单贪心，且满足上限。"""
    import random
    rng = random.Random(7)
    parts = ['轴承', '密封圈', '润滑脂', '滤芯', '垫片', '联轴器']
    for trial_no in range(30):
        kits = [K(i, rng.sample(parts, rng.randint(1, 3))) for i in range(1, 5)]
        jobs = [J(i, rng.sample(parts, rng.randint(1, 3))) for i in range(1, 7)]
        limit = rng.randint(2, 6)
        joint = plan_kitting(jobs, kits, limit)
        greedy = greedy_per_order(jobs, kits, limit)
        assert joint['carried_count'] <= limit
        assert joint['covered'] >= greedy, (trial_no, joint['covered'], greedy)


def test_exact_matches_bruteforce_on_small_cases():
    """小规模与暴力枚举携带集合对拍：覆盖数与闲置数一致。"""
    import random
    rng = random.Random(11)
    parts = ['a', 'b', 'c', 'd']
    for _ in range(20):
        kits = [K(i, rng.sample(parts, rng.randint(1, 3))) for i in range(1, 4)]
        jobs = [J(i, rng.sample(parts, rng.randint(1, 3))) for i in range(1, 5)]
        limit = rng.randint(1, 4)
        best = None
        for size in range(0, limit + 1):
            for t in itertools.combinations(parts, size):
                tset = set(t)
                usable = [k for k in kits if set(k['parts']) <= tset]
                covered = idle = 0
                for j in jobs:
                    need = set(j['parts'])
                    options = []
                    for r in range(1, len(usable) + 1):
                        for combo in itertools.combinations(usable, r):
                            union = set().union(*(set(k['parts']) for k in combo))
                            if need <= union:
                                options.append(len(union - need))
                    if options:
                        covered += 1
                        idle += min(options)
                key = (covered, -idle)
                if best is None or key > best:
                    best = key
        r = plan_kitting(jobs, kits, limit)
        assert (r['covered'], -r['idle_total']) == best


def test_large_seed_like_workload_performance():
    """180 张作业、多包、上限约束下可快速精确求解且结果合法。"""
    import random, time
    rng = random.Random(3108)
    catalog = ['轴承', '密封圈', '润滑脂', '滤芯', '垫片', '联轴器', '皮带', '紧固件', '叶轮', '阀片', '传感器', '清洗剂']
    kits = [K(1, ['轴承', '润滑脂', '密封圈']), K(2, ['紧固件', '垫片', '密封圈']),
            K(3, ['滤芯', '清洗剂']), K(4, ['皮带', '联轴器', '轴承'])]
    jobs = []
    for i in range(180):
        items = set(rng.sample(catalog, rng.randint(1, 3)))
        if i % 3 == 0:
            items.update(['轴承', '润滑脂'])
        if i % 4 == 0:
            items.update(['密封圈', '垫片'])
        if i % 5 == 0:
            items.update(['滤芯', '清洗剂'])
        jobs.append(J(i + 1, items))
    start = time.time()
    r = plan_kitting(jobs, kits, 8)
    assert time.time() - start < 10
    assert r['solver'] == 'exact-enumeration'
    assert r['carried_count'] <= 8
    assert r['covered'] + len(r['uncovered']) == 180
    for a in r['allocations']:                    # 逐件对账：并集 ⊇ 需要件，闲置 = 并集 − 需要件
        assert set(a['required_parts']) <= set(a['union_parts'])
        assert set(a['idle_parts']) == set(a['union_parts']) - set(a['required_parts'])
