"""Observe the exact input and last per-group assignment behind one .rodata section header."""
import prepare_reuse
def apply(src):
    files=prepare_reuse.apply(src);pub=src/'libwild/src';path=pub/'layout.rs'
    s=path.read_text()
    needle='common.store_section_attributes(part_id, header);';assert s.count(needle)==3
    fragments=s.split(needle);out=fragments[0]
    for idx,rest in enumerate(fragments[1:]):
        index='index'if idx==0 else'section_index'
        out+='''if crate::frozen::active() && resources.output_sections.name(part_id.output_section_id::<P>()).is_some_and(|n|n.bytes()==b".rodata") {
                    crate::frozen::ro_input(self.file_id.group(), &self.input,self.object.section_display_name(INDEX),P::section_attributes(header));
                }
                '''.replace('INDEX',index)+needle+rest
    current=out.index('fn propagate_section_attributes')
    before,tail=out[:current],out[current:]
    start='    for group_state in group_states {'
    tail=tail.replace(start,'    for (group_id,group_state) in group_states.iter().enumerate() {',1)
    start='                attributes.apply(output_sections, section_id);'
    assert tail.count(start)==1
    tail=tail.replace(start,'''                if crate::frozen::active() && output_sections.name(section_id).is_some_and(|n|n.bytes()==b".rodata"){
                    crate::frozen::log(format_args!("RO-GROUP\\t{}\\t{:?}",group_id,attributes));
                }
'''+start)
    end=tail.index('\n}',tail.index(start));tail=tail[:end]+'\n    if crate::frozen::active(){crate::frozen::ro_flush();}'+tail[end:];path.write_text(before+tail)
    frozen=pub/'frozen.rs';s=frozen.read_text()+r'''
type Recorded = std::collections::BTreeMap<(usize,String),(usize,String,String)>;
static RO_ROWS: std::sync::OnceLock<std::sync::Mutex<Recorded>>=std::sync::OnceLock::new();
pub(crate) fn ro_input<F:std::fmt::Display,S:std::fmt::Display,A:std::fmt::Debug>(group:usize,file:F,section:S,attr:A){
    let mut rows=RO_ROWS.get_or_init(Default::default).lock().unwrap();
    let row=rows.entry((group,format!("{attr:?}"))).or_insert_with(|| (0,format!("{file}"),format!("{section}")));
    row.0+=1;
}
pub(crate) fn ro_flush(){
    let Some(rows)=RO_ROWS.get()else{return;};
    for ((group,attr),(count,file,section)) in rows.lock().unwrap().iter() {
        log(format_args!("RO-INPUT\t{}\t{}\t{}\t{}\t{}",group,count,file,section,attr));
    }
}
'''
    frozen.write_text(s)
    r=pub/'reuse.rs';s=r.read_text();needle='    if !state().join("coordinate").is_file() {return Ok(None);}'
    assert s.count(needle)==1;r.write_text(s.replace('Duration::from_secs(120)','Duration::from_secs(480)').replace(needle,'    if std::env::var_os("OHM_QA_GROUPS_CHILD").is_some(){return Ok(None);}\n'+needle))
    assert 'libwild/src/layout.rs'not in files
    return files+['libwild/src/layout.rs']
