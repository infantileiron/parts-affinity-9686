"""联合备料优化。

班组按单挑备件包会把重复件种放大。这里把一组作业与已签核备件包联合求解：
每张作业可选多个包，用件取并集；在携带件种上限内，
第一目标最多完整覆盖作业，第二目标最少逐单闲置件总数（字典序）。

件种全集来自 12 项标准目录，因此按件集合位掩码精确枚举携带方案 T（2^|U|），
对每个需求集合用子集和 DP（SOS）求任意 T 下的最小闲置，整体复杂度与作业数线性。
件种规模超过 MAX_EXACT_TYPES 时回退到贪心近似并显式标注 solver。
"""
INF = float('inf')
MAX_EXACT_TYPES = 20  # 标准目录 12 项，正常永远走精确枚举；超出时防御性回退


def _index_universe(jobs, kits):
    universe = sorted({p for j in jobs for p in j['parts']} | {p for k in kits for p in k['parts']})
    return universe, {p: i for i, p in enumerate(universe)}


def _popcount_table(size):
    pop = [0] * size
    for m in range(1, size):
        pop[m] = pop[m >> 1] + (m & 1)
    return pop


def _kit_unions(kit_masks):
    """所有可由包子集拼出的并集 -> 产生它的最少包集合（包索引位掩码）。"""
    unions = {0: 0}
    for ki, pm in enumerate(kit_masks):
        for u, w in list(unions.items()):
            nu, nw = u | pm, w | (1 << ki)
            if nu not in unions or nw.bit_count() < unions[nu].bit_count():
                unions[nu] = nw
    return unions


def _min_cover_unions(unions, need, pop):
    """覆盖 need 的极小并集候选 [(union_mask, idle, witness_kits)]，按闲置升序去支配。"""
    cand = sorted(
        ((u, pop[u] - pop[need], w) for u, w in unions.items() if u & need == need),
        key=lambda c: (c[1], pop[c[0]], c[0]),
    )
    kept = []
    for c in cand:
        if any(k[0] & c[0] == k[0] for k in kept):  # 已有更小并集被它包含 -> 被支配
            continue
        kept.append(c)
    return kept


def _sos_min(kept, size, bits):
    """f[mask] = 候选并集 ⊆ mask 的最小闲置；SOS 子集和 DP。"""
    f = [INF] * size
    for u, idle, _ in kept:
        if idle < f[u]:
            f[u] = idle
    for b in range(bits):
        step = 1 << b
        for m in range(size):
            if m & step:
                alt = f[m ^ step]
                if alt < f[m]:
                    f[m] = alt
    return f


def plan_kitting(jobs, kits, carry_limit):
    """jobs/kits: [{id,code|name,parts:[str]}]，kits 均为已签核。返回可 JSON 序列化的结果。"""
    universe, bit = _index_universe(jobs, kits)
    if len(universe) > MAX_EXACT_TYPES:
        return _greedy_fallback(jobs, kits, carry_limit, universe)

    def mask_of(parts):
        m = 0
        for p in parts:
            m |= 1 << bit[p]
        return m

    kit_masks = [mask_of(k['parts']) for k in kits]
    unions = _kit_unions(kit_masks)
    bits = len(universe)
    size = 1 << bits
    pop = _popcount_table(size)

    groups = {}  # 需求件集合 -> 作业列表（同需求作业共享 DP 表）
    for j in jobs:
        groups.setdefault(mask_of(j['parts']), []).append(j)

    group_list = []
    for need, members in sorted(groups.items()):
        kept = _min_cover_unions(unions, need, pop)
        group_list.append({
            'need': need, 'members': members, 'kept': kept,
            'best_idle': _sos_min(kept, size, bits),
        })

    # 枚举携带件集合 T：先最多完整覆盖，再最少逐单闲置；平局取件种少、掩码小者，保证确定性。
    best_t, best_key = 0, None
    for t in range(size):
        if pop[t] > carry_limit:
            continue
        covered = idle_total = 0
        for g in group_list:
            fi = g['best_idle'][t]
            if fi < INF:
                covered += len(g['members'])
                idle_total += fi
        key = (covered, -idle_total, -pop[t], -t)
        if best_key is None or key > best_key:
            best_key, best_t = key, t
    carried_t = best_t

    # 可用包（⊆T）的并集，用于解释未覆盖原因
    avail = 0
    for pm in kit_masks:
        if pm & carried_t == pm:
            avail |= pm

    def parts_of(mask):
        return [universe[i] for i in range(bits) if mask >> i & 1]

    allocations, uncovered = [], []
    for g in group_list:
        need, members = g['need'], g['members']
        required = parts_of(need)
        fi = g['best_idle'][carried_t]
        if fi < INF:
            union_mask, _, witness = min(
                (c for c in g['kept'] if c[0] & carried_t == c[0] and c[1] == fi),
                key=lambda c: (pop[c[0]], c[0]),
            )
            chosen = [ki for ki in range(len(kits)) if witness >> ki & 1]
            union_parts = parts_of(union_mask)
            idle_parts = [p for p in union_parts if p not in set(required)]
            for j in members:
                allocations.append({
                    'job_id': j['id'], 'code': j['code'],
                    'kit_ids': [kits[ki]['id'] for ki in chosen],
                    'kit_names': [kits[ki]['name'] for ki in chosen],
                    'required_parts': required, 'union_parts': union_parts,
                    'idle_parts': idle_parts,
                })
        else:
            reasons = []
            for i in range(bits):
                if (need & ~avail) >> i & 1:
                    part = universe[i]
                    with_part = [pm for pm in kit_masks if pm >> i & 1]
                    if not with_part:
                        reasons.append({'part': part, 'reason': 'no_approved_kit',
                                        'detail': '没有任何已签核备件包包含该件'})
                    else:
                        extra = min(pop[pm & ~carried_t] for pm in with_part)
                        reasons.append({'part': part, 'reason': 'over_carry_limit',
                                        'detail': f'受携带件种上限 {carry_limit} 约束未携带；含该件的包至少额外引入 {extra} 个件种'})
            for j in members:
                uncovered.append({'job_id': j['id'], 'code': j['code'],
                                  'required_parts': required, 'missing': reasons})

    allocations.sort(key=lambda a: a['job_id'])
    uncovered.sort(key=lambda u: u['job_id'])
    return {
        'solver': 'exact-enumeration',
        'carry_limit': carry_limit,
        'carried_parts': parts_of(carried_t),
        'carried_count': pop[carried_t],
        'covered': len(allocations),
        'total': len(jobs),
        'idle_total': sum(len(a['idle_parts']) for a in allocations),
        'allocations': allocations,
        'uncovered': uncovered,
    }


def _greedy_fallback(jobs, kits, carry_limit, universe):
    """件种规模超出精确枚举上限时的近似：按单位新件种覆盖收益迭代选包。"""
    remaining = set(range(len(jobs)))
    needs = [set(j['parts']) for j in jobs]
    carried, chosen = set(), []
    kit_sets = [set(k['parts']) for k in kits]
    while remaining:
        best = None
        for ki, ks in enumerate(kit_sets):
            if ki in chosen:
                continue
            new_types = ks - carried
            if len(carried) + len(new_types) > carry_limit:
                continue
            gain = sum(1 for j in remaining if needs[j] <= carried | ks)
            key = (gain / max(1, len(new_types)), gain, -len(new_types), -ki)
            if best is None or key > best[0]:
                best = (key, ki)
        if best is None or best[0][1] == 0:
            break
        ki = best[1]
        chosen.append(ki)
        carried |= kit_sets[ki]
        remaining = {j for j in remaining if not needs[j] <= carried}
    allocations, uncovered = [], []
    for j, job in enumerate(jobs):
        if needs[j] <= carried:
            usable = [ki for ki in chosen if kit_sets[ki] & needs[j]]
            union = set().union(*(kit_sets[ki] for ki in usable)) if usable else set()
            allocations.append({
                'job_id': job['id'], 'code': job['code'],
                'kit_ids': [kits[ki]['id'] for ki in usable],
                'kit_names': [kits[ki]['name'] for ki in usable],
                'required_parts': sorted(needs[j]), 'union_parts': sorted(union),
                'idle_parts': sorted(union - needs[j]),
            })
        else:
            missing = sorted(needs[j] - carried)
            uncovered.append({'job_id': job['id'], 'code': job['code'],
                              'required_parts': sorted(needs[j]),
                              'missing': [{'part': p, 'reason': 'over_carry_limit',
                                           'detail': f'近似求解：受携带件种上限 {carry_limit} 约束未携带'} for p in missing]})
    return {
        'solver': 'greedy-fallback',
        'carry_limit': carry_limit,
        'carried_parts': sorted(carried),
        'carried_count': len(carried),
        'covered': len(allocations),
        'total': len(jobs),
        'idle_total': sum(len(a['idle_parts']) for a in allocations),
        'allocations': allocations,
        'uncovered': uncovered,
    }
