            let current_group_input=(|| {
                let mut ranges=Vec::with_capacity(file_loader.loaded_files.len());
                for (slot,file) in file_loader.loaded_files.iter().enumerate(){
                    let raw=file.storage()?.bytes();
                    let base=raw.as_ptr() as usize;
                    ranges.push((base,base.checked_add(raw.len())?,slot,file.filename.as_path()));
                }
                ranges.sort_unstable_by_key(|x|x.0);
                if ranges.windows(2).any(|s|s[0].1>s[1].0){return None;}
                let total=loaded.objects.iter().try_fold(0usize,|acc,o|acc.checked_add(o.as_ref().ok()?.num_symbols()))?;
                let per_group=crate::grouping::determine_symbols_per_group(total,args);
                let file_bound=crate::grouping::determine_max_files_per_group(args);
                let mut values=blake3::Hasher::new();
                let(mut files,mut symbols,mut num_groups)=(0usize,0usize,0usize);
                for (i,obj) in loaded.objects.iter().enumerate(){
                    let obj=obj.as_ref().ok()?;
                    let input=obj.input;let raw=input.data;let at=raw.as_ptr()as usize;
                    let range=ranges.get(ranges.partition_point(|x|x.0<=at).checked_sub(1)?)?;
                    let limit=at.checked_add(raw.len())?;
                    if raw.is_empty() || limit>range.1 || input.file.filename!=range.3 {return None;}
                    let low=at-range.0;let high=limit-range.0;
                    if let Some(entry)=input.entry {
                        if (entry.start_offset,entry.end_offset)!=(low,high){return None;}
                    }else if low!=0 || limit!=range.1{return None;}
                    for u in [range.2,low,high,obj.num_symbols(),usize::from(obj.is_dynamic()),usize::from(input.entry.is_some())]{
                        values.update(&(u as u64).to_le_bytes());
                    }
                    files+=1;symbols=symbols.checked_add(obj.num_symbols())?;
                    let next=loaded.objects.get(i+1).and_then(|o|o.as_ref().ok()).map(|o|o.num_symbols());
                    let finish=files>=file_bound || match next {None=>true,Some(n)=>symbols.checked_add(n)?>per_group};
                    if finish{
                        crate::frozen::log(format_args!("PROJECTED-GROUP\t{}\t{}",files,symbols));
                        (files,symbols)=(0,0);num_groups+=1;
                    }
                }
                if files!=0 || symbols!=0 {return None;}
                Some((total,per_group,file_bound,num_groups,values.finalize()))
            })();
            if let Some((total,per_group,file_bound,num_groups,digest))=&current_group_input{
                crate::frozen::log(format_args!("GROUPINPUT\t{}\t{}\t{}\t{}\t{}",total,per_group,file_bound,num_groups,digest));
            }
