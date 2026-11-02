"""Resolve full DefKey paths, retaining symbol representation and every disambiguator."""
def paths(defs):
 from functools import cache
 @cache
 def path(k):
  if k is None:return ()
  _,parent,kind,symbol,slot=defs[k]
  return path(parent)+((kind,symbol,slot),)
 forward={k:path(k)for k in defs}
 if len(forward)!=len(set(forward.values())):raise ValueError('ambiguous complete native DefKey path')
 return forward,{v:k for k,v in forward.items()}
