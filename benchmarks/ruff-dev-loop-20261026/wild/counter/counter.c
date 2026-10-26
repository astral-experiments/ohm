#include "dr_api.h"
#include "drmgr.h"
#include "drreg.h"
#include <stdint.h>
#include <sys/syscall.h>

static process_id_t root_pid;
static file_t output;
static void *event_lock;
static reg_id_t segment;
static uint offset;
static int tls_index;

static void check(bool ok) {
    if (!ok) dr_abort();
}

static void record(char event, void *dc, uint64_t value) {
    if (dr_get_process_id() != root_pid) return;
    dr_mutex_lock(event_lock);
    dr_fprintf(output, "%c %d %d %llu\n", event, (int)root_pid,
               dc == NULL ? 0 : (int)dr_get_thread_id(dc), (unsigned long long)value);
    dr_mutex_unlock(event_lock);
}

static void thread_start(void *dc) {
    uint64_t *count = (uint64_t *)((byte *)dr_get_dr_segment_base(segment) + offset);
    *count = 0;
    check(drmgr_set_tls_field(dc, tls_index, count));
    record('T', dc, 0);
}

static void thread_exit(void *dc) {
    uint64_t *count = drmgr_get_tls_field(dc, tls_index);
    record('F', dc, *count);
}

static bool syscall_filter(void *dc, int num) {
    return num == SYS_execve || num == SYS_execveat;
}

static bool pre_syscall(void *dc, int num) {
    if (syscall_filter(dc, num)) record('E', dc, num);
    return true;
}

static dr_signal_action_t on_signal(void *dc, dr_siginfo_t *sig) {
    record('S', dc, (uint64_t)sig->sig);
    return DR_SIGNAL_DELIVER;
}

static dr_emit_flags_t count_block(void *dc, void *tag, instrlist_t *bb,
                                   bool trace, bool translating, void **data) {
    ptr_uint_t count = 0;
    for (instr_t *ins = instrlist_first_app(bb); ins; ins = instr_get_next_app(ins))
        ++count;
    *data = (void *)count;
    return DR_EMIT_DEFAULT;
}

static dr_emit_flags_t insert_count(void *dc, void *tag, instrlist_t *bb, instr_t *where,
                                    bool trace, bool translating, void *data) {
    if (!drmgr_is_first_instr(dc, where) || data == NULL) return DR_EMIT_DEFAULT;
    check(drreg_reserve_aflags(dc, bb, where) == DRREG_SUCCESS);
    instrlist_meta_preinsert(bb, where, INSTR_CREATE_add(dc, dr_raw_tls_opnd(dc, segment, offset),
                                   OPND_CREATE_INT32((int)(ptr_uint_t)data)));
    check(drreg_unreserve_aflags(dc, bb, where) == DRREG_SUCCESS);
    return DR_EMIT_DEFAULT;
}

static void process_exit(void) {
    record('P', NULL, 0);
    if (dr_get_process_id() == root_pid) dr_close_file(output);
    drreg_exit();
    drmgr_exit();
}

DR_EXPORT void dr_client_main(client_id_t id, int argc, const char *argv[]) {
    check(argc == 2 && drmgr_init());
    drreg_options_t opts = { sizeof(opts), 1, false };
    check(drreg_init(&opts) == DRREG_SUCCESS);
    check(dr_raw_tls_calloc(&segment, &offset, 1, 0));
    tls_index = drmgr_register_tls_field();
    check(tls_index >= 0);
    root_pid = dr_get_process_id();
    event_lock = dr_mutex_create();
    output = dr_open_file(argv[1], DR_FILE_WRITE_REQUIRE_NEW | DR_FILE_CLOSE_ON_FORK);
    check(output != INVALID_FILE);
    record('B', NULL, 0);
    check(drmgr_register_filter_syscall_event(syscall_filter));
    check(drmgr_register_pre_syscall_event(pre_syscall));
    check(drmgr_register_signal_event(on_signal));
    check(drmgr_register_thread_init_event(thread_start));
    check(drmgr_register_thread_exit_event(thread_exit));
    check(drmgr_register_bb_instrumentation_event(count_block, insert_count, NULL));
    drmgr_register_exit_event(process_exit);
}
