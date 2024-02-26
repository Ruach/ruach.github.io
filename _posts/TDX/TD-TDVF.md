## TDVF Binary Image Format
### Boot Firmware Volume (BFV)
>The TDVF includes one Firmware Volume (FV) known as the BFV. The FV format is 
>defined in the UEFI Platform Initialization (PI) specification. The BFV 
>includes all TDVF components required during boot.
>1. TdResetVector: provides the entrypoint for TDVF.
>2. TdDxeIpl: prepares required parameter for DxeCore and jumps to DxeCore.
>3. DxeCore: this is standard DxeCore, used in standard UEFI firmware. it 
>dispatches all DXE modules.
>4. DXE Modules: TDVF-specific modules to initialize TDVF environment and launch
>OS loader. 

### Configuration Firmware Volume (CFV)
???



## TDVF Boot Flow
[TDVF General Flow]



### VCPU mode transitions
VCPU executs in 32 bit protected mode when TDX module launches TDVF. Because TDX 
operations such as TDCALL is only available when it executes in long mode, the 
TDVF first switches mode of the current VCPU to long mode. Also the private page
and page tables related mmu features are available when it runs in long mode.


## Information from VMM to TDVF
### TD Hand-Off Block (HOB)
The TD HOB list passes the information from VMM to TDVF. The format of HOB is 
defined in PI spec. TDVF must include PHIT HOB and Resource Descriptor HOB. The
TDVF must create its own DXE HOB based on TD HOB and pass the DXE HOB to the DXE
core. 

### Resource description HOB
The TD HOB must include at least one Resource Description HOB to declare the 
physical memory resource assigned to the TD VM. Any DRAM memory reported by the
HOB should be accepted by the TDVF except for Temporary memory and TD HOB 
regions, which are declared in the TD metadata. The resource HOB can optionally
report MMIO and IO regions based on the guest hardware provided by the VMM.

[TDVF Initial Memory Layout]



## TDVF implementation on QEMU side
\XXX{Need another section for this?}
TD-VM launches follows below steps.
1. VMM loads TDVF to TD VM, which is measured into MRTD
2. Call TDX module to launch TDVF inside TD VM
3. TDVF boots and enables UEFI secure boot
4. TDVF prepares TD event log and launches OS loader


### Load TDVF to GPA
The VMM calls TDX module to initialize TD memory for TDVF. This initial memory 
includes firmware code and UEFI secure boot configuration.

**hw/core/generic-loader.c**
```cpp
 66 static void generic_loader_realize(DeviceState *dev, Error **errp)
 67 {
 68     GenericLoaderState *s = GENERIC_LOADER(dev);
......
140     if (s->file) {      
141         AddressSpace *as = s->cpu ? s->cpu->as :  NULL;
142 
143         if (!s->force_raw) {
144             size = load_elf_as(s->file, NULL, NULL, NULL, &entry, NULL, NULL,
145                                NULL, big_endian, 0, 0, 0, as);
146                
147             if (size < 0) {
148                 size = load_uimage_as(s->file, &entry, NULL, NULL, NULL, NULL,
149                                       as);
150             }
151 
152             if (size < 0) {
153                 size = load_tdvf(s->file, s->config_firmware_volume);
154             }
155 
156             if (size < 0) {
157                 size = load_targphys_hex_as(s->file, &entry, as);
158             }
159         }       
```

```cpp
333 int load_tdvf(const char *filename, const char *config_firmware_volume)
334 {
......
397     if (tdvf_parse_metadata_header(fw, fd, &metadata) < 0) {
398         close(fd);
399         return -1;
400     }
401 
402     tdvf_parse_metadata_entries(fd, fw, &metadata);
```

```cpp
 44         
 45 #define TDVF_SIGNATURE_LE32     0x46564454 /* TDVF as little endian */
 46     
 47 typedef struct {
 48     uint8_t Signature[4];
 49     uint32_t Length;
 50     uint32_t Version;
 51     uint32_t NumberOfSectionEntries;
 52     TdvfSectionEntry SectionEntries[];
 53 } TdvfMetadata;
```

First **tdvf_parse_metadata_header** reads the header and verifies whether it is
TDVF file. As a result of the parsing, it retrieves the TdvfMetadata struct. 
Note that this struct contains general information of tdvf binaries such as 
number of sections consisting of the tdvf binary and length of the header. After
the verification and metadata read, to parse each section of TDVF binary, it 
invokes **tdvf_parse_metadata_entries** function.

```cpp
192 static void tdvf_parse_metadata_entries(int fd, TdxFirmware *fw,
193                                         const TdvfMetadata *metadata)
194 {
195 
196     TdvfSectionEntry *sections;
197     ssize_t entries_size;
198     uint32_t len, i;
199 
200     fw->nr_entries = le32_to_cpu(metadata->NumberOfSectionEntries);
201     if (fw->nr_entries < 2) {
202         error_report("Invalid number of entries (%u) in TDVF", fw->nr_entries);
203         exit(1);
204     }
205 
206     len = le32_to_cpu(metadata->Length);
207     entries_size = fw->nr_entries * sizeof(TdvfSectionEntry);
208     if (len != sizeof(*metadata) + entries_size) {
209         error_report("TDVF metadata len (0x%x) mismatch, expected (0x%x)",
210                      len, (uint32_t)(sizeof(*metadata) + entries_size));
211         exit(1);
212     }
213 
214     fw->entries = g_new(TdxFirmwareEntry, fw->nr_entries);
215     sections = g_new(TdvfSectionEntry, fw->nr_entries);
216 
217     if (read(fd, sections, entries_size) != entries_size)  {
218         error_report("Failed to read TDVF section entries");
219         exit(1);
220     }
221 
222     for (i = 0; i < fw->nr_entries; i++) {
223         tdvf_parse_section_entry(&fw->entries[i], &sections[i],
224                                  fw->file_size + fw->cfv_size);
225     }
226     g_free(sections);
227 }
```

```cpp
typedef struct {
    uint32_t DataOffset;
    uint32_t RawDataSize;
    uint64_t MemoryAddress;
    uint64_t MemoryDataSize;
    uint32_t Type;
    uint32_t Attributes;
} TdvfSectionEntry;

typedef struct TdxFirmwareEntry {                                           
    uint32_t data_offset;                                                   
    uint32_t data_len;                                                      
    uint64_t address;                                                       
    uint64_t size;                                                          
    uint32_t type;                                                          
    uint32_t attributes;                                                    
                                                                            
    MemoryRegion *mr;                                                       
    void *mem_ptr;                                                          
} TdxFirmwareEntry;  
```

**section** variable on the above code points to the raw memory of the tdvf 
section headers. The **tdvf_parse_section_entry** function parses sections and
translate each code section of the TDVF binary into TdxFirmwareEntry which will
be used to allocate memory pages for TDVF binary. 

```cpp
static void tdvf_parse_section_entry(TdxFirmwareEntry *entry,
                                     const TdvfSectionEntry *src,
                                     uint64_t file_size)
{

    entry->data_offset = le32_to_cpu(src->DataOffset);
    entry->data_len = le32_to_cpu(src->RawDataSize);
    entry->address = le64_to_cpu(src->MemoryAddress);
    entry->size = le64_to_cpu(src->MemoryDataSize);
    entry->type = le32_to_cpu(src->Type);
    entry->attributes = le32_to_cpu(src->Attributes);
```


### Allocate memory for TDVF sections 
```cpp
333 int load_tdvf(const char *filename, const char *config_firmware_volume)
334 {
......
404     for_each_fw_entry(fw, entry) {
405         entry->mem_ptr = qemu_ram_mmap(-1, size, qemu_real_host_page_size, 0, 0);
406         if (entry->mem_ptr == MAP_FAILED) {
407             error_report("failed to allocate memory for TDVF");
408             exit(1);
409         }
410         if (entry->address < x86ms->below_4g_mem_size ||
411             entry->address > 4 * GiB) {
412             tdvf_init_ram_memory(ms, entry);
413         } else {
414             tdvf_init_bios_memory(fd, filename, cfv_fd, cfv_size,
415                                   config_firmware_volume, entry);
416         }
417     }
```

After parsing the all sections of TDVF binary, we have information such as 
section size and base address. Note that we did not map the memory and load the 
TDVF binary to the memory based on the section information yet. It iterates the
section information and allocates the memory and load TDVF sections one by one.

```cpp
 38 static void tdvf_init_ram_memory(MachineState *ms, TdxFirmwareEntry *entry)
 39 {
 40     X86MachineState *x86ms = X86_MACHINE(ms);
 41 
 42     if (entry->type == TDVF_SECTION_TYPE_BFV ||
 43         entry->type == TDVF_SECTION_TYPE_CFV) {
 44             error_report("TDVF type %u addr 0x%" PRIx64 " in RAM (disallowed)",
 45                          entry->type, entry->address);
 46             exit(1);
 47     }
 48 
 49     if (entry->address >= 4 * GiB) {
 50         /*
 51          * If TDVF temp memory describe in TDVF metadata lays in RAM, reserve
 52          * the region property.
 53          */
 54         if (entry->address >= 4 * GiB + x86ms->above_4g_mem_size ||
 55             entry->address + entry->size >= 4 * GiB + x86ms->above_4g_mem_size) {
 56             error_report("TDVF type %u address 0x%" PRIx64 " size 0x%" PRIx64
 57                          " above high memory",
 58                          entry->type, entry->address, entry->size);
 59             exit(1);
 60         }
 61     }
 62     e820_change_type(entry->address, entry->size, E820_ACCEPTED);
 63 }
```


```cpp
65 static void tdvf_init_bios_memory(
 66     int fd, const char *filename, int cfv_fd, off_t cfv_size,
 67     const char *cfv_name, TdxFirmwareEntry *entry)
 68 {
 69     static unsigned int nr_cfv;
 70     static unsigned int nr_tmp;
 71 
 72     MemoryRegion *system_memory = get_system_memory();
 73     Error *err = NULL;
 74     const char *name;
 75 
 76     /* Error out if the section might overlap other structures. */
 77     if (entry->address < 4 * GiB - 16 * MiB) {
 78         error_report("TDVF type %u address 0x%" PRIx64 " in PCI hole",
 79                         entry->type, entry->address);
 80         exit(1);
 81     }
 82 
 83     if (entry->type == TDVF_SECTION_TYPE_BFV) {
 84         name = g_strdup("tdvf.bfv");
 85     } else if (entry->type == TDVF_SECTION_TYPE_CFV) {
 86         name = g_strdup_printf("tdvf.cfv%u", nr_cfv++);
 87     } else if (entry->type == TDVF_SECTION_TYPE_TD_HOB) {
 88         name = g_strdup("tdvf.hob");
 89     } else if (entry->type == TDVF_SECTION_TYPE_TEMP_MEM) {
 90         name = g_strdup_printf("tdvf.tmp%u", nr_tmp++);
 91     } else {
 92         error_report("TDVF type %u unknown/unsupported", entry->type);
 93         exit(1);
 94     }
 95     entry->mr = g_malloc(sizeof(*entry->mr));
 96 
 97     memory_region_init_ram(entry->mr, NULL, name, entry->size, &err);
 98     if (err) {
 99         error_report_err(err);
100         exit(1);
101     }
102 
103     memory_region_add_subregion(system_memory, entry->address, entry->mr);
104 
105     if (entry->type == TDVF_SECTION_TYPE_TEMP_MEM) {
106         e820_add_entry(entry->address, entry->size, E820_ACCEPTED);
107     }
108 
109     if (entry->data_len) {
110         int tfd = fd;
111         const char *tfilename = filename;
112         off_t offset = entry->data_offset;
113         if (cfv_fd != -1) {
114             /*
115              * Adjust file offset and which file to read, when TDVF is split
116              * into two files, TDVF_VARS.fd and TDVF_CODE.fd.
117              * TDVF.fd =
118              *   file offset = 0
119              *   TDVF_VARS.fd(CFV)
120              *   file offset = cfv_size
121              *   TDVF_CODE.fd(BFV)
122              *   file end
123              */
124             if (offset >= cfv_size) {
125                 tfd = fd;
126                 tfilename = filename;
127                 offset -= cfv_size;
128             } else if (offset + entry->data_len <= cfv_size) {
129                 tfd = cfv_fd;
130                 tfilename = cfv_name;
131             } else {
132                 /* tdvf entry shouldn't cross over CFV and BFV. */
133                 error_report("unexpected tdvf entry cfv %s %lx bfv %s "
134                              "offset %x size %x",
135                              cfv_name, cfv_size, filename,
136                              entry->data_offset, entry->data_len);
137                 exit(1);
138             }
139         }
140 
141         if (lseek(tfd, offset, SEEK_SET) != offset) {
142             error_report("can't seek to 0x%lx %s", offset, tfilename);
143             exit(1);
144         }
145         if (read(tfd, entry->mem_ptr, entry->data_len) != entry->data_len) {
146             error_report("can't read 0x%x %s", entry->data_len, tfilename);
147             exit(1);
148         }
149     }
150 }

```

The most important parts of the above function is generating new memory regions
for each tdvf section and add it as a sub-region of the TD-VM memory region.
First it needs to allocate memory (memory_region_init_ram), called RAMBlock for
the memory region. The address of the RAMBlock is the HVA mapped to the GPA.
memory_region_add_subregion function allows the TD-VM reserves GPA memory region 
pointed to by its parameter entry->address (GPA of TDVF section). Precisely 
speaking, it does not reserve the GPA, but the memslot translating GPA to the 
allocated RAMBlock is generated on the KVM side. This is important because we 
need HPA of the GPA where we want to load the TDVF sections, and GPA should be 
translated into the HVA first through the memslot. Without this information, KVM
cannot copy the memory from the source (fw->mem_ptr) to the target TD-VM page 
which will be specified in GPA format (entry->address). 

Note that the raw data read from each section of the tdvf is stored in 
entry->mem_ptr, not in the allocated RAMBlock by the memory_region_init_ram,
which means that the read binaries should be loaded to the RAMBlock later, but 
before the TD-VM entrance to tdvf. This is related with KVM_TDX_INIT_MEM_REGION 
ioctl (refer to xxx).

