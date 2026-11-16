import math,json,hashlib
from itertools import combinations
VERSION='apriori-max3-v1'
def mine(rows,min_support=.15,min_confidence=.6,min_lift=1):
 transactions=[frozenset(r['parts']) for r in rows if r.get('parts')]
 n=len(transactions)
 if n<2:raise ValueError('至少需要2条含备件的有效维保作业')
 if not 0<min_support<=1 or not 0<min_confidence<=1 or min_lift<0:raise ValueError('无效阈值')
 minimum=math.ceil(n*min_support-1e-12);universe=sorted(set().union(*transactions))
 counts={};level=[]
 for part in universe:
  key=frozenset([part]);count=sum(key<=t for t in transactions)
  if count>=minimum:counts[key]=count;level.append(key)
 for size in (2,3):
  candidates={a|b for a in level for b in level if len(a|b)==size}
  candidates={c for c in candidates if all(frozenset(s) in counts for s in combinations(sorted(c),size-1))}
  level=[]
  for c in sorted(candidates,key=lambda c:tuple(sorted(c))):
   count=sum(c<=t for t in transactions)
   if count>=minimum:counts[c]=count;level.append(c)
 rules=[]
 for itemset,count in counts.items():
  if len(itemset)<2:continue
  for size in range(1,len(itemset)):
   for a_tuple in combinations(sorted(itemset),size):
    a=frozenset(a_tuple);b=itemset-a;support=count/n;confidence=count/counts[a];lift=confidence/(counts[b]/n)
    if confidence+1e-12>=min_confidence and lift+1e-12>=min_lift:
     rules.append({'signature':','.join(sorted(a))+'->'+','.join(sorted(b)),'antecedent':sorted(a),'consequent':sorted(b),'count':count,'support':support,'confidence':confidence,'lift':lift})
 rules.sort(key=lambda r:(-r['lift'],-r['confidence'],-r['support'],r['signature']))
 frequent=[{'items':sorted(k),'count':v,'support':v/n} for k,v in counts.items()]
 return dict(valid_jobs=n,excluded=len(rows)-n,minimum_count=minimum,frequent=frequent,rules=rules,version=VERSION,checksum=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),method='Apriori最大项集长度3；每张有效作业为一个事务，重复备件去重；support=count(A∪B)/N；confidence=count(A∪B)/count(A)；lift=confidence/support(B)。关联不代表必须联换，需核对设备、兼容性与备件数量。')
