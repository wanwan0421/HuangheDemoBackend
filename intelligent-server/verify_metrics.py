from evaluation import metrics

# test 1
retrieved=['a','b','c']
gold={'a'}
rel_map={'a':2}
print('dcg@1=', metrics.dcg_at_k(retrieved,gold,1,rel_map))
print('idcg@1=', metrics.idcg_at_k(len(gold),1,[2]))
print('ndcg@1=', metrics.ndcg_at_k(retrieved,gold,1,rel_map))

# test 2
retrieved2=['g2','g1','g3']
gold2={'g1','g2','g3'}
rel_map2={'g1':2,'g2':1,'g3':0}
print('dcg@3=', metrics.dcg_at_k(retrieved2,gold2,3,rel_map2))
print('idcg@3=', metrics.idcg_at_k(3,3,[2,1,0]))
print('ndcg@3=', metrics.ndcg_at_k(retrieved2,gold2,3,rel_map2))
