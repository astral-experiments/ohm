"""Select the single native incremental-directory option and preserve all other operands."""

def without_incremental(argv):
    result=[]
    removed=[]
    i=0
    while i<len(argv):
        if argv[i]=="-C" and i+1<len(argv) and argv[i+1].startswith("incremental="):
            removed.append(argv[i+1]);i+=2
        elif argv[i].startswith("-Cincremental="):
            removed.append(argv[i][2:]);i+=1
        else:
            result.append(argv[i]);i+=1
    if len(removed)!=1 or not removed[0].removeprefix("incremental=").startswith("/"):
        raise ValueError("missing or ambiguous absolute native incremental option")
    return result
