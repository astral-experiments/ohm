set -eu
cd "$(dirname "$0")"
mkdir -p vglib
for p in /usr/libexec/valgrind/*; do f=${p##*/}; test -e "vglib/$f" || ln -s "$p" "vglib/$f"; done
cc -O2 -Wall -I/usr/include/valgrind -DVGA_amd64 -DVGO_linux -DVGP_amd64_linux -DVGPV_amd64_linux_vanilla -fno-stack-protector -fno-pie -fno-builtin -c probe.c -o probe.o
cc -no-pie -static -nostartfiles -nodefaultlibs -nostdlib -Wl,-Ttext-segment=0x58000000 -Wl,-z,now -Wl,-e,_start -o vglib/cgured-amd64-linux probe.o -L/usr/lib/x86_64-linux-gnu/valgrind -Wl,--start-group -lcoregrind-amd64-linux -lvex-amd64-linux -lvexmultiarch-amd64-linux -lgcc-sup-amd64-linux -lgcc -Wl,--end-group

cc -O2 -std=gnu11 -Wall -Wextra -Werror capture.c -lcrypto -o capture
cc -shared -fPIC -O2 -std=gnu11 -Wall -Wextra -Werror launch.c -lcrypto -o launch.so
