            if let Some((bytes, donor))=crate::reuse::request(args.output(),safe)? {
                let start=std::time::Instant::now();
                crate::reuse::start_fresh_creation();
                output.set_size(bytes.len() as u64);
                let write_result=output.with_output_bytes(|s|{s.out.copy_from_slice(&bytes);Ok(())});
                let collision=crate::reuse::finish_fresh_creation();
                if collision {
                    if write_result.is_ok(){crate::bail!("exclusive output collision unexpectedly wrote");}
                    crate::frozen::log(format_args!("MISS\toutput-exclusive-collision"));
                } else {
                    write_result?;
                    if crate::reuse::published_new_generation(&donor,args.output())? {
                        crate::frozen::log(format_args!("FRESH-PUBLISH\t{}\t{}",bytes.len(),start.elapsed().as_nanos()));
                        return Ok(LinkerOutput::empty());
                    }
                    crate::frozen::log(format_args!("MISS\toutput-generation-not-published"));
                }
                // The one-shot writer has been consumed. Let the original complete native
                // linker create its own writer after a conflicting publisher changed the name.
                output=file_writer::Output::new::<P>(args,output_kind,self.file_system.clone());
            }
