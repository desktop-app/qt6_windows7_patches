import struct
import sys

KEEP_DELAY = {
    'api-ms-win-core-winrt-l1-1-0.dll',
    'api-ms-win-core-winrt-error-l1-1-0.dll',
    'api-ms-win-core-winrt-string-l1-1-0.dll',
    'api-ms-win-eventlog-legacy-l1-1-0.dll',
    'api-ms-win-core-console-l1-1-0.dll',
    'api-ms-win-core-fibers-l2-1-0.dll',
    'api-ms-win-core-fibers-l2-1-1.dll',
    'api-ms-win-core-file-l1-1-0.dll',
    'api-ms-win-core-localization-l1-2-0.dll',
    'api-ms-win-core-memory-l1-1-0.dll',
    'api-ms-win-core-memory-l1-1-1.dll',
}


class Pe(object):
    def __init__(self, data):
        self.data = data
        if data[:2] != b'MZ':
            raise ValueError('not MZ')
        pe = struct.unpack_from('<I', data, 0x3C)[0]
        if data[pe:pe + 4] != b'PE\x00\x00':
            raise ValueError('not PE')
        coff = pe + 4
        machine, nsec = struct.unpack_from('<HH', data, coff)
        sizeopt = struct.unpack_from('<H', data, coff + 16)[0]
        opt = coff + 20
        magic = struct.unpack_from('<H', data, opt)[0]
        if magic == 0x20B:
            ddoff = opt + 112
            self.imagebase = struct.unpack_from('<Q', data, opt + 24)[0]
            self.thunk = (8, 63)
        elif magic == 0x10B:
            ddoff = opt + 96
            self.imagebase = struct.unpack_from('<I', data, opt + 28)[0]
            self.thunk = (4, 31)
        else:
            raise ValueError('bad optional header magic 0x%X' % magic)
        ndirs = struct.unpack_from('<I', data, ddoff - 4)[0]
        self.dirs = []
        for i in range(ndirs):
            self.dirs.append(struct.unpack_from('<II', data, ddoff + 8 * i))
        self.sections = []
        st = opt + sizeopt
        for i in range(nsec):
            base = st + 40 * i
            vsize, vaddr, rawsize, rawptr = struct.unpack_from(
                '<IIII', data, base + 8)
            self.sections.append((vaddr, max(vsize, rawsize), rawptr))

    def rva(self, rva, size=1):
        for vaddr, vspan, rawptr in self.sections:
            if vaddr <= rva and rva + size <= vaddr + vspan:
                off = rawptr + (rva - vaddr)
                if off + size <= len(self.data):
                    return off
        raise ValueError('rva 0x%X out of sections' % rva)

    def cstr(self, rva, limit=4096):
        off = self.rva(rva)
        end = self.data.find(b'\x00', off, off + limit)
        if end < 0:
            raise ValueError('unterminated string at rva 0x%X' % rva)
        return self.data[off:end].decode('latin-1')

    def imports(self):
        rva, size = self.dir(1)
        if not rva:
            return []
        out = []
        pos = self.rva(rva)
        end = pos + size
        while pos + 20 <= end:
            offt, _, _, nameRva, fthunk = struct.unpack_from(
                '<IIIII', self.data, pos)
            if not (offt or nameRva or fthunk):
                break
            dll = self.cstr(nameRva)
            thunkRva = offt or fthunk
            tsize, ordbit = self.thunk
            i = 0
            while True:
                entry = struct.unpack_from(
                    '<Q' if tsize == 8 else '<I',
                    self.data, self.rva(thunkRva + i * tsize))[0]
                if not entry:
                    break
                if entry & (1 << ordbit):
                    out.append((dll, '#%d' % (entry & 0xFFFF), True))
                else:
                    out.append((dll, self.cstr(entry + 2), False))
                i += 1
            pos += 20
        return out

    def delay_dlls(self):
        rva, size = self.dir(13)
        if not rva:
            return []
        out = []
        pos = self.rva(rva)
        end = pos + size
        while pos + 32 <= end:
            fields = struct.unpack_from('<8I', self.data, pos)
            if not any(fields):
                break
            grAttrs, szName = fields[0], fields[1]
            if grAttrs & ~1:
                break
            if not (grAttrs & 1):
                szName -= self.imagebase
            out.append(self.cstr(szName))
            pos += 32
        return out

    def dir(self, index):
        if index < len(self.dirs):
            return self.dirs[index]
        return (0, 0)

    def exports(self):
        rva, size = self.dir(0)
        if not rva:
            return (0, [])
        e = self.rva(rva)
        (_, _, _, _, _, _, nfuncs, nnames,
         afRva, anRva, aoRva) = struct.unpack_from(
            '<IIHHIIIIIII', self.data, e)
        base = struct.unpack_from('<I', self.data, e + 16)[0]
        slots = [None] * nfuncs
        for i in range(nfuncs):
            frva = struct.unpack_from('<I', self.data,
                                      self.rva(afRva + 4 * i))[0]
            if not frva:
                continue
            if rva <= frva and frva < rva + size:
                slots[i] = (None, self.cstr(frva))
            else:
                slots[i] = (None, None)
        for i in range(nnames):
            name = self.cstr(struct.unpack_from(
                '<I', self.data, self.rva(anRva + 4 * i))[0])
            oi = struct.unpack_from('<H', self.data, self.rva(aoRva + 2 * i))[0]
            if oi >= nfuncs:
                raise ValueError('export ordinal out of range')
            if slots[oi] is not None:
                slots[oi] = (name, slots[oi][1])
        return (base, slots)


def split_forwarder(text, known):
    dots = [i for i, ch in enumerate(text) if ch == '.']
    for i in dots:
        candidate = text[:i].lower()
        for form in (candidate, candidate + '.dll'):
            if form in known:
                return text[:i], text[i + 1:]
    i = text.rfind('.')
    if i > 0:
        return text[:i], text[i + 1:]
    return None, None


def load_db(path):
    entries = {}
    absent = set()
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) == 2 and parts[1] == 'ABSENT-ON-WIN7':
            absent.add(parts[0].lower())
            continue
        if len(parts) < 2:
            raise ValueError('bad db line: %r' % line)
        key = (parts[0].lower(), parts[1])
        entries[key] = (parts[2].lower(), parts[3]) if len(parts) >= 4 else None
    return entries, absent, {dll for dll, _ in entries} | absent


def resolve(entries, dll, func, depth=0):
    if depth > 8:
        return False
    tgt = entries.get((dll, func))
    if tgt is None:
        return (dll, func) in entries
    tdll, tfunc = tgt
    if not tdll.endswith('.dll'):
        tdll += '.dll'
    return resolve(entries, tdll, tfunc, depth + 1)


def check(exe_path, db_path):
    entries, absent, known = load_db(db_path)
    data = open(exe_path, 'rb').read()
    pe = Pe(data)
    imports = pe.imports()
    delay = [d.lower() for d in pe.delay_dlls()]
    problems = []
    imported = {}
    for dll, func, is_ord in imports:
        imported.setdefault(dll.lower(), []).append((func, is_ord))
    for dll in sorted(imported):
        funcs = imported[dll]
        if dll in absent:
            problems.append('DLL-ABSENT-ON-WIN7 %s' % dll)
            continue
        if dll not in known:
            problems.append('DLL-NOT-IN-DB %s' % dll)
            continue
        for func, is_ord in funcs:
            if not resolve(entries, dll, func):
                problems.append('MISSING %s %s' % (dll, func))
    for dll in sorted(set(delay)):
        if dll not in KEEP_DELAY:
            problems.append('DELAY-OUTSIDE-KEEP-LIST %s' % dll)
    total = sum(len(v) for v in imported.values())
    print('WIN7 GATE: exe=%s db=%s' % (exe_path, db_path))
    print('imports: %d functions / %d dlls (load-time), delay dlls: %d'
          % (total, len(imported), len(set(delay))))
    for line in problems:
        print(line)
    print('GATE: %s (%d problem(s))' % (
        'FAIL' if problems else 'PASS', len(problems)))
    return 1 if problems else 0


def main(argv):
    if len(argv) >= 3 and argv[1] == 'check':
        return check(argv[2], argv[3])
    if len(argv) >= 3 and argv[1] == 'exports':
        for path in argv[2:]:
            base, slots = Pe(open(path, 'rb').read()).exports()
            mod = path.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
            for i, slot in enumerate(slots):
                if slot is None:
                    continue
                name, fwd = slot
                if name:
                    print('%s %s%s' % (mod, name,
                                       ' FWD %s' % fwd if fwd else ''))
                print('%s #%d%s' % (mod, base + i,
                                    ' FWD %s' % fwd if fwd else ''))
        return 0
    print('usage: check_imports.py check <exe> <db> | exports <dll>...')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
