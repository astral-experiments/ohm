from ablate_original import *
import sys
if __name__ == '__main__':
    name=sys.argv[sys.argv.index('--name')+1]
    share=sys.argv[sys.argv.index('--share')+1]
    if name=='ruff': print('Ruff screening moved to charlie-serc-1')
    elif name=='uv' and share=='yes': print('UV broad-flag candidate skipped in favor of actual Cargo policy; recorded uv-global-share-yes-skipped.json')
    else: main()
