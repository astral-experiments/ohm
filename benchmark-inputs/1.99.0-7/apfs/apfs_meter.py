"""Measure an isolated APFS volume without double-counting cloned extents."""
import ctypes, fcntl, json, os, plistlib, struct, subprocess, time
from pathlib import Path

class AttrList(ctypes.Structure):
    _fields_=[('bitmapcount',ctypes.c_ushort),('reserved',ctypes.c_ushort),('commonattr',ctypes.c_uint32),('volattr',ctypes.c_uint32),('dirattr',ctypes.c_uint32),('fileattr',ctypes.c_uint32),('forkattr',ctypes.c_uint32)]

def native_used(path):
    attr=AttrList(5,0,0,0x80000000|0x00800000,0,0,0)
    buffer=ctypes.create_string_buffer(32)
    libc=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
    libc.getattrlist.argtypes=[ctypes.c_char_p,ctypes.POINTER(AttrList),ctypes.c_void_p,ctypes.c_size_t,ctypes.c_ulong]
    if libc.getattrlist(os.fsencode(path),ctypes.byref(attr),buffer,len(buffer),0x4):
        error=ctypes.get_errno();raise OSError(error,os.strerror(error),str(path))
    length,used=struct.unpack_from('=IQ',buffer.raw)
    if length!=12:raise RuntimeError('Unexpected getattrlist payload length: '+str(length))
    return used

def diskutil(path):
    info=plistlib.loads(subprocess.check_output(['diskutil','info','-plist',str(path)]))
    if info.get('FilesystemType')!='apfs':raise RuntimeError('Expected APFS')
    data=plistlib.loads(subprocess.check_output(['diskutil','apfs','list','-plist']))
    for container in data['Containers']:
        for volume in container['Volumes']:
            if volume['DeviceIdentifier']==info['DeviceIdentifier']:
                return {'volume_bytes':volume['CapacityInUse'],'container_bytes':container['CapacityCeiling']-container['CapacityFree'],'device':volume['DeviceIdentifier'],'container':container['ContainerReference'],'volume_uuid':volume['APFSVolumeUUID']}
    raise RuntimeError('Volume absent from APFS container inventory')

def flush(path):
    marker=Path(path)/'.measurement-flush'
    with marker.open('ab') as output:
        output.flush();os.fsync(output.fileno());fcntl.fcntl(output.fileno(),51)
    subprocess.run(['sync'],check=True)

def sample(path,baseline=0,crosscheck=True):
    first=native_used(path)
    check=diskutil(path) if crosscheck else {}
    last=native_used(path)
    if crosscheck and not min(first,last)<=check['volume_bytes']<=max(first,last):
        # diskutil and getattrlist can observe distinct APFS transaction commits.
        check['between_native_samples']=False
    elif crosscheck:check['between_native_samples']=True
    return {'time':time.time(),'native_bytes':last,'retained_bytes':last-baseline,'crosscheck':check}

def stable(path,baseline=0,idle_seconds=30):
    started=time.monotonic();time.sleep(idle_seconds);flush(path)
    readings=[]
    for _ in range(120):
        reading=sample(path,baseline);readings.append(reading)
        if len(readings)>=5 and len({x['native_bytes'] for x in readings[-5:]})==1 and all(x['crosscheck']['between_native_samples'] for x in readings[-5:]):
            return {'idle_seconds':time.monotonic()-started,'samples':readings,'endpoint':readings[-1]}
        time.sleep(1)
    raise RuntimeError('APFS allocation did not stabilize')

def create(image,mount,name,size='180g'):
    image=Path(image);mount=Path(mount)
    if image.exists() or mount.exists():raise RuntimeError('APFS destination already exists')
    image.parent.mkdir(parents=True,exist_ok=True);mount.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['hdiutil','create','-size',size,'-fs','APFS','-type','SPARSE','-volname',name,str(image)],check=True)
    mount.mkdir()
    attached=plistlib.loads(subprocess.check_output(['hdiutil','attach','-nobrowse','-owners','on','-mountpoint',str(mount),'-plist',str(image)]))
    assert any(x.get('mount-point')==str(mount) for x in attached['system-entities'])
    (mount/'.metadata_never_index').touch()
    flush(mount)
    baseline=stable(mount,idle_seconds=5)
    return {'image':str(image),'mount':str(mount),'attach':attached,'baseline':baseline}
