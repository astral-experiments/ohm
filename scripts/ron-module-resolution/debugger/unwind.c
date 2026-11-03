#define UNW_LOCAL_ONLY_DO_NOT_USE
#include <libunwind.h>
#include <libunwind-ptrace.h>
#include <stdint.h>
int walk(int tid, uint64_t *ips, int n) {
    unw_addr_space_t as = unw_create_addr_space(&_UPT_accessors, 0);
    if (!as) return -100;
    void *pt = _UPT_create(tid);
    unw_cursor_t c;
    int k = 0, rc = unw_init_remote(&c, as, pt);
    while (rc >= 0 && k < n) {
        unw_word_t ip = 0;
        rc = unw_get_reg(&c, UNW_REG_IP, &ip);
        if (rc < 0 || ip == 0) break;
        ips[k++] = ip;
        rc = unw_step(&c);
        if (rc <= 0) break;
    }
    _UPT_destroy(pt);
    unw_destroy_addr_space(as);
    return k ? k : rc;
}
