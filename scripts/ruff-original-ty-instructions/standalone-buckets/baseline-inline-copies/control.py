"""Exercise a genuine exported owner plus equal text whose two relocation targets differ."""
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import census

def main():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);units={}
        for unit,visibility,callee in (("a","static","first"),("b","static","second"),("g","","first")):
            source=root/(unit+".c");image=root/(unit+".o")
            source.write_text("extern int "+callee+"(int);\n"+visibility+" __attribute__((used,noinline)) int same(int a){return a+1;}\n"
                              +visibility+" __attribute__((used,noinline)) int branch(int a){return "+callee+"(a);}\n")
            subprocess.run(["cc","-O0","-ffunction-sections","-fno-stack-protector","-c",source,"-o",image],check=True)
            units[unit]=census.functions(image.read_bytes())
        out=census.aggregate(units,{"a"})["ranges"]
        assert out["all_affected_local"]["function_rows"]==2
        assert out["same_local_name_other_unit"]["function_rows"]==2
        assert out["same_local_name_bytes_and_relocations_other_unit"]["function_rows"]==1
        assert out["same_name_identical_machine_link_and_external_elsewhere"]["function_rows"]==2
        del units["g"]
        assert census.aggregate(units,{"a"})["ranges"]["same_local_name_also_external_elsewhere"]["function_rows"]==0

if __name__=="__main__":
    main()
