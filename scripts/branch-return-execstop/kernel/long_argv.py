"""Install one image with a non-UTF or special-character-bearing 98,003-byte binary argument."""
import os, pathlib, sys
here=pathlib.Path(__file__).resolve().parent
os.chdir(sys.argv[1] if len(sys.argv)>1 else here)
word=b"A\tB\nC'\xff"*14000+b"end"
os.execve('./relative-exe', [b'custom argv[0]',word,b'',b''], os.environ)
