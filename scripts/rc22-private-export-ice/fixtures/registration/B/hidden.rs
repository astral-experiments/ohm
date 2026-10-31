extern "C" fn install(){super::VALUE.store(83,core::sync::atomic::Ordering::SeqCst);}
#[used]
#[unsafe(export_name = "ohm_retained_hook_bbbb")]
#[unsafe(link_section = ".init_array")]
static REGISTER: extern "C" fn() = install;
