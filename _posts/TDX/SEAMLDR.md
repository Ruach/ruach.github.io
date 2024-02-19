Secure Arbitration Mode (SEAM) is an extension of Virtual Machines Extension 
(VMX). It introduces new VMX root mode called SEAM root. The primary goal of 
this new root mode is to host a CPU-attested module, called TDX module, to 
create Trust Domains (TD), which is the secure VM instance protected from other
system components including host VMM. 

Software that executes in **SEAM root mode**, defined by SEAM range registers 
(SEAMRR). The SEAM range is partitioned into two sub-ranges: MODULE_RANGE and 
P_SEAMLDR_RANGE. Therefore, only the p_seamldr and TDX module can run as SEAM
root mode. 

Virtual machines launched/resumed from SEAM VMX root operation are TDs, and VMs
launched/resumed from legacy VMX root operation are legacy VMs. When processor
runs TD, it runs in another newly introduced CPU mode, **SEAM VMX non root.**

The NP-SEAMLDR ACM helps with the initialization of the SEAM range, establishes
the P-SEAMLDR range, sets up the SEAM transfer VMCS structure for transfers to 
the Intel P-SEAMLDR module, and loads the **embedded** Intel P-SEAMLDR module's 
image into the P_SEAMLDR_RANGE. Therefore, loading NP-SEAMLDR on the platform 
will automatically load the P_SEAMLDR too.

Because P_SEAMLDR is installed in the SEAMRR range, CPU needs to enter VMX SEAM
root mode through SEAMCALL to execute P_SEAMLDR for loading TDX Module. The TDX
module is loaded to the MODULE_RANGE by the P_SEAMLDR and provides functions to
build and manages TD-VMs. 

[[https://github.gatech.edu/sslab/tdx/blob/main/img/SEAMLDR.png]]



# NP-Seamldr
NP-Seamldr is provided as an authenticated code module (AC). The primary goal is
loading P-Seamldr to the SEAMRR range. 

### Authenticated Code Modules (ACMs)
Intel TDX utilize feature of [Intel TXT][TXT] to securely load the NP-SEAMLDR
and P-SEAMLDR to the memory, which guarantees only **Intel signed Intel TDX 
loaders** can be loaded into the memory. 
Specifically, ACM is a module digitally signed by the Intel that contain code to
be run before the traditional x86 CPU reset vector. The ACMs can be invoked 
through the GETSEC instruction, too.


### Things to be done by NP-Seamldr
The NP-SEAMLDR ACM is designed to follow the steps below to load or update the
Intel P-SEAMLDR module into the Persistent SEAMLDR range in SEAMRR:
1. Perform basic checks on current state of platform.
2. **Initialize the entire SEAM memory range.**
3. **Install the embedded P-SEAMLDR module in the P-SEAMLDR memory range.**
4. Set up data and stack regions for the Intel P-SEAMLDR module.
5. **Set up a single SEAM transfer VMCS*
6. Update the load status of the Intel P-SEAMLDR module.
7. Exit to OS using the GETSEC[EXITAC] instruction

[[https://github.gatech.edu/sslab/tdx/blob/main/img/SEAMCALL_ENTER.png]]
### VMCS as a gateway connecting VMM & SEAM
VMCS has been used for entering and exiting the VM from host VMM. However, Intel
TDX repurposes the VMCS so that it can be utilized during CPU mode changes 
between VMM to SEAM. In software perspective, VMCS bridges host VMM and Intel 
TDX module. Also, it bridges the VMM and P-SEAMLDR. To this end, Intel TDX 
introduces SEAMCALL and SEAMRET instructions and make the processor utilize the
VMCS embedded in TDX module and P-SEAMLDR during the mode switch. 

Because host VMM to P-SEAMLDR and TDX module interface utilize the SEAMCALL and 
SEAMRET instructions, the MSB of the rax register is used to determines where 
the SEAMCALL and SEAMRET exit and return to (1 for P-seamldr, 0 for TDX module).
Also, the transition from the VMX Root to SEAM VMX Root is presented as an **VM 
exit \& enter**. Following the original semantic of VMX Root operation, when the 
VM exit or enter happens it jumps to the predetermined code location specified 
in the VMCS. TDX cannot believe the VMM layer so SEAMCALL switches to the VMCS 
residing in the SEAMRR range where the VMM cannot access. As a result, the 
SEAMCALL can jump to the pre-programmed locations securely. The location of the
VMCS used by the SEAMCALL and SEAMRET instructions are fixed by the TDX 
specification. VMCS for P-SEAMLDR and TDX module are initialized by 
the NP-SEAMLDR and P-SEAMLDR, respectively following the spec. 

```c
VMCS_FOR_TDX = IA32_SEAMRR_PHYS_BASE + 4096 + CPUID.B.0.EDX [31:0] * 4096.
```

For example, the location of the VMCS for TDX module is determined based on
which logical processor the seamcall instruction is invoked on.



The OS can launch the SEAMLDR ACM using the GETSEC[ENTERACCS] instruction if the
SEAMRR range enable bit(bit 11) of the IA32_SEAMRR_PHYS_MASK MSR is 1.

## Deep dive into NP-SEAMLDR

```cpp
void ProjectAcmEntryPoint()
{   
    PT_CTX PtCtx;
    
    Init64bitComArea();

    SeamldrCom64Data.OriginalCR4 = OriginalCR4;
    SeamldrCom64Data.HeaderStart = (UINT64)&HeaderStart;
    SeamldrCom64Data.PseamldrOffset = (UINT64)&PSeamldrAsm;
    SeamldrCom64Data.PseamldrSize = PSeamldrSizeAsm;
    SeamldrCom64Data.PseamldrConstsOffset = (UINT64)&PSeamldrConstAsm;
    SeamldrCom64Data.OriginalES = OriginalES & 0x0FF8;
    SeamldrCom64Data.OriginalFS = OriginalFS & 0x0FF8;
    SeamldrCom64Data.OriginalGS = OriginalGS & 0x0FF8;
    SeamldrCom64Data.OriginalSS = OriginalSS & 0x0FF8;
    SeamldrCom64Data.OriginalECX = OriginalECX & 0x0FF8;

    MemFill((UINT8*)&SeamldrPagingTable, sizeof(SEAMLDR_PAGING_TABLE_T), 0);
    
    EstablishSeamldrPaging(&SeamldrCom64Data, &PtCtx);

    SeamldrCom64Data.PtCtxPtr = (UINT64)&PtCtx; 
    
    SeamldrThunk64();
    
    // No return to here
}
```
The most first function is the ProjectAcmEntryPoint. Before this function some 
assembly code sets up the stack and others to run C code. 

### Initializing Paging
The first thing that needs to be done before running main program is enabling 
paging.

```cpp
// ;---------------------------------------------------------------------------- -
// ; Input tables are sorted like that from the base :
// ; 0x0 - PML5 base - entry at index 0 points to PML4 base
// ; 0x1000 - PML4 base - entry at index 0 points to PDPT base
// ; 0x2000 - PDPT base - entries at indices 0 - 3 point to the 4 PD tables - which can cover the whole low 4 GB space
// ; 0x3000 - PD table 0
// ; 0x4000 - PD table 1
// ; 0x5000 - PD table 2
// ; 0x6000 - PD table 3
// ; 0x7000 - PT table 0 - used for 1 to 1 mapping of the ACM
// ; 0x8000 - PT table 1 - used for 1 to 1 mapping of the ACM
// ; 0x9000 - PT table 2 - used for all other 4K mappings in the system. (not necessary 1 to 1)
// ;---------------------------------------------------------------------------- -
typedef struct {
    IA32E_PAGING_TABLE_T Pml5;
    IA32E_PAGING_TABLE_T Pml4;
    IA32E_PAGING_TABLE_T Pdpt;
    IA32E_PAGING_TABLE_T Pd[4]; 
    IA32E_PAGING_TABLE_T Pt[3];
} SEAMLDR_PAGING_TABLE_T;
```


```cpp
__declspec(align(4096)) SEAMLDR_PAGING_TABLE_T SeamldrPagingTable;

PT_CTX* EstablishSeamldrPaging(SEAMLDR_COM64_DATA *pCom64, IN OUT PT_CTX * PtCtx)
{
    COM_DATA* PE2BIN_Com_Data = (COM_DATA*)((UINT32)AcmEntryPoint - sizeof(COM_DATA));
    // We will use index 0 for PML5 and PML4 because we aren't going to map linear addresses above 4GB
    MapPagingStructure(&SeamldrPagingTable.Pml5.PT[0], &SeamldrPagingTable.Pml4);
    MapPagingStructure(&SeamldrPagingTable.Pml4.PT[0], &SeamldrPagingTable.Pdpt);

    // First indexes 0-3 in PDPT covers the whole lower 4 GB (each PD table cover 512 entries of 2MB, there are 4 PD tables)
    MapPagingStructure(&SeamldrPagingTable.Pdpt.PT[0], &SeamldrPagingTable.Pd[0]);
    MapPagingStructure(&SeamldrPagingTable.Pdpt.PT[1], &SeamldrPagingTable.Pd[1]);
    MapPagingStructure(&SeamldrPagingTable.Pdpt.PT[2], &SeamldrPagingTable.Pd[2]);
    MapPagingStructure(&SeamldrPagingTable.Pdpt.PT[3], &SeamldrPagingTable.Pd[3]);

    // We will fill the entries in PD tables later, at this point they are empty and don't map anything

    // Now we need to establish 1-to-1 paging for the SEAMLDR ACM address space
    // We need to map data/stack pages with XD (execute disabled) bit, and code pages as read-only
    // The structure of the ACM is as follows (from low addresses to high):
    // 32-bit data and stack
    // 32-bit code
    // 64-bit data
    // 64-bit code
    // These offsets are stored in COM_DATA

    // Only bits 30:31 are relevant for low 4GB
    UINT32 PdptIdx = ((AcmBase >> 30) & 0x3);
    // Mask the 9 index bits
    UINT32 PdIdx = ((AcmBase >> 21) & 0x1FF);

    IA32E_PAGING_TABLE_T* Pd = &SeamldrPagingTable.Pd[PdptIdx];

    MapPagingStructure(&Pd->PT[PdIdx], &SeamldrPagingTable.Pt[0]);

    UINT32 PtIdx = ((AcmBase >> 12) & 0x1FF);
    UINT32 LastPtIdx = PtIdx + (rounded(AcmSize, PAGE_SIZE) / PAGE_SIZE);
    UINT64 CurrentAcmPageToMap = AcmBase;

    IA32E_PAGING_TABLE_T* Pt = &SeamldrPagingTable.Pt[0];

    // Map the ACM 4K pages until the last index in the PT table (must be 1:1 mapping)
    for (UINT32 i = PtIdx; i < ((LastPtIdx < 512) ? LastPtIdx : 512); i++) {
        if (IsCodeAcmPage(PE2BIN_Com_Data, CurrentAcmPageToMap))
        {
            Map4KPage(&Pt->PT[i], CurrentAcmPageToMap, FALSE, TRUE, TRUE); // Not-writable, WB memtype, Executable
        }
        else
        {
            Map4KPage(&Pt->PT[i], CurrentAcmPageToMap, TRUE, TRUE, FALSE); // Writable, WB memtype, Non-executable
        }
        CurrentAcmPageToMap += PAGE_SIZE;
    }

    if (LastPtIdx > 512) {
        // In case when the Acm mapping spans over two page tables, we need to map the PtTable1 in the PD
        // However there's also a possibility that we were on our last slot in the current PD, so we need to switch to the next one
        if (PdIdx == 511) {
            // We won't span over the 4GB boundary in Acm, so it's ok to just +1 the PDPT index
            PdptIdx = PdptIdx + 1;
            Pd = &SeamldrPagingTable.Pd[PdptIdx];
            PdIdx = 0;
        }
        else {
            PdIdx = PdIdx + 1;
        }

        MapPagingStructure(&Pd->PT[PdIdx], &SeamldrPagingTable.Pt[1]);

        Pt = &SeamldrPagingTable.Pt[1];

        PtIdx = 0;
        LastPtIdx = LastPtIdx - 512;

        // Map the rest of the ACM 4K pages
        for (UINT32 i = PtIdx; i < LastPtIdx; i++) {
            if (IsCodeAcmPage(PE2BIN_Com_Data, CurrentAcmPageToMap))
            {
                Map4KPage(&Pt->PT[i], CurrentAcmPageToMap, FALSE, TRUE, TRUE); // Not-writable, WB memtype, Executable
            }
            else
            {
                Map4KPage(&Pt->PT[i], CurrentAcmPageToMap, TRUE, TRUE, FALSE); // Writable, WB memtype, Non-executable
            }
            CurrentAcmPageToMap += PAGE_SIZE;
        }
    }

    // One of the unused PD table will be used for rest of the 4K mappings in the system (not necessary 1 to 1)
    PdptIdx = (PdptIdx + 1) % 4;
    Pd = &SeamldrPagingTable.Pd[PdptIdx];

    // We will use only the first index in the unused PD table for the PT Table 2
    // And we won't touch the rest of the indexes, to prevent confusion
    MapPagingStructure(&Pd->PT[0], &SeamldrPagingTable.Pt[2]);

    // Virtual base is calculated as follows:
    // PML5 and PML4 index is 0. PDPT index as chosen. PD index 0, PT index is 0
    PtCtx->VirtualBaseFor4KMappings = (PdptIdx << 30);
    PtCtx->PtBaseFor4KMappings = (UINT64)&SeamldrPagingTable.Pt[2];
    PtCtx->NextFreePtIdx = 0;

    // The last (third or fourth) unused PD table will be used for 2MB mapping in the system (not necessary 1 to 1)
    // This table will cover 512 * 2MB space, which 1GB, which should be enough to map the entire SEAMRR
    PdptIdx = (PdptIdx + 1) % 4;

    // Virtual base is calculated as follows:
    // PML5 and PML4 index is 0. PDPT index as chosen. PD index 0
    PtCtx->VirtualBaseFor2MBMappings = (PdptIdx << 30);
    PtCtx->PdBaseFor2MBMappings = (UINT64)&SeamldrPagingTable.Pd[PdptIdx];
    PtCtx->NextFreePdIdx = 0;

    // Prior to enabling paging, the SEAMLDR should configure the IA32_PAT MSR with its reset default value 0x0007040600070406 (i.e.PAT0 = WB, PAT7 = UC).
    writeMsr(MSR_IA32_PAT, 0x00070406UL, 0x00070406UL);

    // Load CR3 with the PML4/5 base - the SEAMLDR will run with either 4-level or 5-level paging, depending on the original level of the OS
    if (SeamldrCom64Data.OriginalCR4 & CR4_LA57) {
        __writecr3(&SeamldrPagingTable.Pml5);
    }
    else {
        __writecr3(&SeamldrPagingTable.Pml4);
    }

    // Set EFER.LME to re-enable ia32-e
    UINT32 RDX, RAX;
    readMsr(IA32_EFER_MSR, &RDX, &RAX);
    RAX |= (LME | N_IA32_EFER_NXE);
    writeMsr(IA32_EFER_MSR, RDX, RAX);

    // Enable paging
    __writecr0(__readcr0() | CR0_PG | CR0_WP);

    return PtCtx;
}
```

The NP-seamldr is very simple program to load the seamldr to the SEAMRR memory 
range. To this end, it first need to be able to execute the main program of the 
NP-seamldr and needs page table mappings. Because the main body of NP-seamldr is
already loaded into physical address range [AcmBase, AcmBase+AcmSize], it only
needs page table mappings for those region for execution. 
However, during the NP-seamldr execution, it needs to map data already placed in
the physical memories, it needs additional page table entries, 4K and 2M sized
pages. Because it initializes very limited number of page tables, the virtual 
addresses covered by those page tables can only be used, which means the further
physical addresses will always be mapped to specific virtual addresses. 

```cpp
UINT64 MapPhysicalRange(PT_CTX *pctx, UINT64 Addr, UINT64 size, PAGE_ACCESS_TYPE IsWritable, PAGE_SIZE PageMappingSize, PAGE_CACHING_TYPE IsWBMemtype)
{
    UINT32 i = 0;
    UINT32 PagesToMap = 0;
    UINT64 Base = 0;
    UINT64 VirtualAddr = 0;
    UINT64 OffsetInPage = 0;

    if (PageMappingSize == PAGE_2M) {

        Base = Addr & _2MB_MASK;
        OffsetInPage = Addr & (_2MB - 1);
        PagesToMap = rounded((OffsetInPage + size), _2MB) / _2MB;

        if (pctx->NextFreePdIdx + PagesToMap > 512) {
            ComSerialOut("No free 2MB entries left to map the range");
            return BAD_MAPPING;
        }

        IA32E_PAGING_TABLE_T* Pd = (IA32E_PAGING_TABLE_T*)pctx->PdBaseFor2MBMappings;

        VirtualAddr = pctx->VirtualBaseFor2MBMappings + (pctx->NextFreePdIdx * _2MB) + OffsetInPage;

        for (i = 0; i < PagesToMap; i++, pctx->NextFreePdIdx++, Base += _2MB) {
            Map2MBPage(&Pd->PT[pctx->NextFreePdIdx], Base, IsWritable, IsWBMemtype);
        }
    }
    else {

        Base = Addr & _4KB_MASK;
        OffsetInPage = Addr & (_4KB - 1);
        PagesToMap = rounded((OffsetInPage + size), _4KB) / _4KB;

        if (pctx->NextFreePtIdx + PagesToMap > 512) {
            ComSerialOut("No free 4KB entries left to map the range");
            return BAD_MAPPING;
        }

        IA32E_PAGING_TABLE_T* Pt = (IA32E_PAGING_TABLE_T*)pctx->PtBaseFor4KMappings;

        VirtualAddr = pctx->VirtualBaseFor4KMappings + (pctx->NextFreePtIdx * _4KB) + OffsetInPage;

        for (i = 0; i < PagesToMap; i++, pctx->NextFreePtIdx++, Base += _4KB) {
            Map4KPage(&Pt->PT[pctx->NextFreePtIdx], Base, IsWritable, IsWBMemtype);
        }
    }

    return VirtualAddr;
}
```

Note that PtBaseFor4KMappings and VirtualBaseFor2MBMappings are used depending 
on the page size used for mapping. These two variables are set to point to 4K
and 2M page table, respectively, during the page table initialization.

### Jump to the main function
```cpp
SeamldrThunk64 PROC NEAR  
        ;
        ; System in compatibility mode
        ;
        mov     ecx, ACM_CODE64_SELECTOR ;ACM64_CODE
        push    ecx                     ; push ecx - in 32 bit mode

        mov     ecx, OFFSET LongMode
        push    ecx                     ; push ecx - in 32 bit mode
        retf                            ; will jump to LongMode label below
        ;
        ; Long mode.
        ;
LongMode:
        db      48h, 0B8h
        dq      0FFFFFFFFh              ; mov   rax, 00000000FFFFFFFFh
        db      48h, 21h, 0C4h          ; and   rsp, rax
        ;
        ; Call 64-bit entry point
        ;
        mov     esi, OFFSET AcmEntryPoint
        db      48h, 21h, 0C6h          ; and   rsi, rax

        mov     ebx, cs:[esi - SIZEOF COM_DATA].COM_DATA.Code64Entry
        db      48h, 21h, 0C3h          ; and   rbx, rax

        mov     ecx, OFFSET SeamldrCom64Data
        db      48h, 21h, 0C1h          ; and   rcx, rax

        call    ebx                     ; call rbx   


```

```cpp
Entry64 PROC FRAME
        START_FRAME
        MAKE_LOCAL   pCom64data:QWORD
        MAKE_LOCAL   pIdt64[2]:QWORD
        END_FRAME

        ;
        ; Save entry parameter
        ;
        mov     pCom64data, rcx

        mov     rcx, pCom64data
        ; backup registers
        mov     QWORD PTR [rcx].SEAMLDR_COM64_DATA.OriginalR8, r8
        mov     QWORD PTR [rcx].SEAMLDR_COM64_DATA.OriginalR9, r9
        mov     QWORD PTR [rcx].SEAMLDR_COM64_DATA.OriginalR10, r10
        mov     QWORD PTR [rcx].SEAMLDR_COM64_DATA.OriginalR11, r11
        mov     QWORD PTR [rcx].SEAMLDR_COM64_DATA.OriginalR12, r12

        ; zero non-input registers
        mov     r13, 0
        mov     r14, 0
        mov     r15, 0

        ; Align the stack pointer to 16-byte before running the main 64-bit code - required from proper crypto usage
        and     rsp, 0fffffff0h
        sub     rsp, 20h

        call    Target64

        ;; SEAMLDR64 finished running here.
        ;; Exit procedure:

        mov     rcx, pCom64data
```


```cpp
//-----------------------------------------------------------------------------
// ACM - PE2BIN communication area
//-----------------------------------------------------------------------------
typedef struct _COM_DATA {
    UINT32 Data64Start;                   // Offset of 64-bit data start (and Code32End)
    UINT32 Code64Start;                   // Offset of 64-bit code start
    UINT32 Code64End;                     // Offset of 64-bit code end
    UINT32 Code64Entry;                   // Offset of 64-bit code entry point
    UINT32 StkStart;                      // Offset of stack start
    UINT32 Code32Start;                   // Offset of code segment start.
} COM_DATA;


    COM_DATA < \
            OFFSET HeaderStart, \
            OFFSET HeaderStart, \
            OFFSET HeaderStart, \
            OFFSET HeaderStart, \
            OFFSET stackStart,  \
            OFFSET HeaderStart \
            >
```

```cpp
void Target64 (SEAMLDR_COM64_DATA *pCom64)
{
    UINT64 canonicity_mask = 0;
    __security_init_cookie();
    pCom64->NewIDTR.Limit = pCom64->OriginalIDTRLimit;
    pCom64->NewIDTR.Base = pCom64->OriginalR12;
    *(UINT64 *)(pCom64->OriginalGdtr + 2) = pCom64->OriginalR9;
    pCom64->ResumeRip   = pCom64->OriginalR10;
    pCom64->OriginalCR3 = pCom64->OriginalR11;
    
    PT_CTX* PtCtx = (PT_CTX*)pCom64->PtCtxPtr;
    
    CloseTPMLocality(PtCtx);
    canonicity_mask = ((pCom64->OriginalCR4 & CR4_LA57) != 0) ? CANONICITY_MASK_5LP : CANONICITY_MASK_4LP;
    if (((pCom64->ResumeRip & canonicity_mask) != 0) && ((pCom64->ResumeRip & canonicity_mask) != canonicity_mask)) {
        _ud2();
    }

    SeamldrAcm(pCom64, PtCtx);
    ReopenTPMLocality(PtCtx);
    *(UINT16*)pCom64->NewGdtr = 0xFFF;
    *(UINT64*)(pCom64->NewGdtr + 2) = (UINT64)TempGdt;
    *(UINT64*)(TempGdt + pCom64->OriginalES) = GdtBasePtr.AcmDataDescriptor.Raw;
    *(UINT64*)(TempGdt + pCom64->OriginalFS) = GdtBasePtr.AcmDataDescriptor.Raw;
    *(UINT64*)(TempGdt + pCom64->OriginalGS) = GdtBasePtr.AcmDataDescriptor.Raw;
    *(UINT64*)(TempGdt + pCom64->OriginalSS) = GdtBasePtr.AcmDataDescriptor.Raw;
    *(UINT64*)(TempGdt + pCom64->OriginalECX) = GdtBasePtr.AcmCode64Descriptor.Raw;
}

```


### XXX
```cpp
void SeamldrAcm(SEAMLDR_COM64_DATA *pCom64, PT_CTX* PtCtx) {
    ......
    SeamrrBaseMsr.raw = readMsr64(MSR_IA32_SEAMRR_BASE);
    SeamrrMaskMsr.raw = readMsr64(MSR_IA32_SEAMRR_MASK);
    ......
    SeamldrData.TdxPrivateKidMask = KidBitMask << ((UINT64)GetMaxPhyAddr() - NumTdxPrivateBits);

    SeamldrData.SeamrrBase = (SeamrrBaseMsr.raw & B_SEAMRR_BASE);
    SeamldrData.SeamrrSize = ~(shiftLeft64(SeamrrMaskMsr.mask, N_SEAMRR_MASK_MASK) | SeamldrData.TdxPrivateKidMask | (~SeamldrData.MaximumSupportMemAddress)) + 1;
    ......
    // Map the SysInfoTable as a single 4KB page with UC memtype
    SeamldrData.PSysInfoTable = (P_SYS_INFO_TABLE_t*)MapPhysicalRange(PtCtx, SeamldrData.SeamrrBase + SeamldrData.SeamrrSize - PAGE4K, PAGE4K, PAGE_WRITABLE, PAGE_4K, PAGE_UC_MEMTYPE);

    PRINT_HEX_VAL("SeamldrData.SysInfoTable->PSeamldrRange.Size: 0x", SeamldrData.PSysInfoTable->PSeamldrRange.Size);
    PRINT_HEX_VAL("SeamldrData.PSeamldrConsts->CCodeRgnSize: 0x", SeamldrData.PSeamldrConsts->CCodeRgnSize);
    PRINT_HEX_VAL("SeamldrData.PSeamldrConsts->CDataStackSize: 0x", SeamldrData.PSeamldrConsts->CDataStackSize);
    PRINT_HEX_VAL("SeamldrData.PSeamldrConsts->CDataRgnSize: 0x", SeamldrData.PSeamldrConsts->CDataRgnSize);
    ......
    SeamldrData.AslrRand = (((UINT64)(Rrrr & ASLR_MASK)) << 32);
    ......
    Status = LoadModuleCode((UINT8*) pCom64->PseamldrOffset, pCom64->PseamldrSize);
    if (Status != NP_SEAMLDR_PARAMS_STATUS_SUCCESS) {
        ComSerialOut("Loading P-Seamldr code failed\n");
        goto EXIT;
    }
    
    InitPseamldrPtCtx(&SeamrrPtCtx, SeamldrData.SeamrrVa, SeamldrData.SeamrrBase, SeamldrData.SeamrrSize, SeamldrData.PSysInfoTable->PSeamldrRange.Base, CPagingStructSize);

    Status = RelocateImage(SeamldrData.SeamrrVaLimit - (SeamldrData.PSeamldrConsts->CCodeRgnSize + C_P_SYS_INFO_TABLE_SIZE), C_CODE_RGN_BASE | SeamldrData.AslrRand);
    if (Status != NP_SEAMLDR_PARAMS_STATUS_SUCCESS) {
        ComSerialOut("Failed to relocate P-Seamldr\n");
        goto EXIT;
    };  
    
    Status = MapModulePages(&SeamrrPtCtx, pCom64->PseamldrSize);
    if (Status != NP_SEAMLDR_PARAMS_STATUS_SUCCESS) {
        ComSerialOut("Failed to map module pages\n");
        goto EXIT;
    };

    ComSerialOut("Setup stacks\n");
    Status = SetupStacks(&SeamrrPtCtx);
    if (Status != NP_SEAMLDR_PARAMS_STATUS_SUCCESS) {
        ComSerialOut("Failed to setup stacks\n");
        goto EXIT;
    };  
    ComSerialOut("Setup keyhole\n");
    //    DEBUG ((EFI_D_INFO, ("Setup keyhole\n"));
    Status = SetupKeyholeMapping(&SeamrrPtCtx);
    if (Status != NP_SEAMLDR_PARAMS_STATUS_SUCCESS) {
        ComSerialOut("Failed to setup keyholes\n");
        goto EXIT;
    };
    
    ComSerialOut("Setup Data Region\n");
    Status = SetupDataRegion(&SeamrrPtCtx);
    if (Status != NP_SEAMLDR_PARAMS_STATUS_SUCCESS) {
        ComSerialOut("Failed to setup data region\n");
        goto EXIT;
    };

    // map system information tables
    ComSerialOut("Map SysInfoTable\n");
    Status = MapSysInfoTables(&SeamrrPtCtx);
    if (Status != NP_SEAMLDR_PARAMS_STATUS_SUCCESS) {
        goto EXIT;
    }

    ComSerialOut("Setup Module Region\n");
    Status = MapModuleRegion(&SeamrrPtCtx);
    if (Status != NP_SEAMLDR_PARAMS_STATUS_SUCCESS) {
        ComSerialOut("Failed to map Module Region!\n");
        goto EXIT;
    }


    ComSerialOut("Setup PSysinfo table\n");
    SetupSysInfoTable();

    ComSerialOut("Setup VMCS\n");
    SetupVmcs(SeamrrPtCtx.PtBaseAddrPa);
```

### Loading P-SEAMLDR
```cpp
SEAMRR_PT_CTX* InitPseamldrPtCtx(OUT SEAMRR_PT_CTX* SeamrrPtCtx, UINT64 SeamRrVa, UINT64 SeamRrBase, UINT64 SeamRrSize, UINT64 PSeamldrRangeBase, UINT64 PagingStructSize)
{
    ComSerialOut("InitSeamrrPtCtx\n");
    PRINT_HEX_VAL("SeamRrBase: 0x", SeamRrBase);
    PRINT_HEX_VAL("SeamRrSize: 0x", SeamRrSize);

    SeamrrPtCtx->PtBaseAddrLa = SeamRrVa + (PSeamldrRangeBase - SeamRrBase) + _8KB;
    SeamrrPtCtx->PtBaseAddrPa = SeamRrBase + (PSeamldrRangeBase - SeamRrBase) + _8KB;

    SeamrrPtCtx->PtAllocatorPa = SeamrrPtCtx->PtBaseAddrPa + _4KB;
    SeamrrPtCtx->NumPageLevels = 4;

    SeamrrPtCtx->VPDelta = SeamRrVa - SeamRrBase;

    SeamrrPtCtx->PagingStructSize = PagingStructSize;
```

### Setup pagetable and memory region for P-SEAMLDR
Until now, we have used the MapPhysicalRange function to map the physical pages
to the virtual addresses which can be accessible inside the NP-SEAMLDR. For this 
we have set the page tables for NP-SEAMLDR. However, the page tables and mapped
virtual address should not be shared between the NP and P SEAMLDR. Also, because
SEAMCALL interface utilize the VM exit interface to enter P-SEAMLDR, instead of 
making the P-SEAMLDR revisit all the step we did go through in the NP-SEAMLDR,
NP-SEAMLDR can prepare page tables and memory regions during its initialization.
Following the below equation, the root page table address is determined. 

```cpp
SeamrrPtCtx->PtBaseAddrPa = SeamRrBase + (PSeamldrRangeBase - SeamRrBase) + _8KB;
```

Also, the NP-SEAMLDR prepared some memory regions for P-SEAMLDR such as stack, 
keyhole, data region, &c. Because those memory regions are should be accessible 
by the P-SEAMLDR, not by NP-SEAMLDR, it is useless to generate mapping for the 
NP-SEAMLDR. Therefore, it populates mapping for those regions P-SEAMLDR's page
table using MapPage function. It walks the P-SEAMLDR's page table and allocate
mapping for the passed virtual addresses. With this efforts, the P-SEAMLDR can 
accesses it code and data regions without going through all initial steps such 
as page table initialization. Also, the P-SEAMLDR's binary is mapped using the 
same function, MapPage.

### Setup SysInfo table for P-SEAMLDR
```cpp
void SetupSysInfoTable() {
    SeamldrData.PSysInfoTable->CodeRgn.Base = C_CODE_RGN_BASE | SeamldrData.AslrRand;
    SeamldrData.PSysInfoTable->CodeRgn.Size = SeamldrData.PSeamldrConsts->CCodeRgnSize;
    SeamldrData.PSysInfoTable->DataRgn.Base = C_DATA_RGN_BASE | SeamldrData.AslrRand;
    SeamldrData.PSysInfoTable->DataRgn.Size = SeamldrData.PSeamldrConsts->CDataRgnSize;
    SeamldrData.PSysInfoTable->StackRgn.Base = C_STACK_RGN_BASE | SeamldrData.AslrRand;
    SeamldrData.PSysInfoTable->StackRgn.Size = SeamldrData.PSeamldrConsts->CDataStackSize + P_SEAMLDR_SHADOW_STACK_SIZE;
    SeamldrData.PSysInfoTable->KeyholeRgn.Base = C_KEYHOLE_RGN_BASE | SeamldrData.AslrRand;
    SeamldrData.PSysInfoTable->KeyholeRgn.Size = SeamldrData.PSeamldrConsts->CKeyholeRgnSize;
    SeamldrData.PSysInfoTable->KeyholeEditRgn.Base = C_KEYHOLE_EDIT_REGION_BASE | SeamldrData.AslrRand;
    SeamldrData.PSysInfoTable->KeyholeEditRgn.Size = SeamldrData.PSeamldrConsts->CKeyholeEditRgnSize;
    SeamldrData.PSysInfoTable->ModuleRgnBase = C_MODULE_RGN_BASE | SeamldrData.AslrRand;
    SeamldrData.PSysInfoTable->AcmX2ApicId = GetX2ApicId();
    SeamldrData.PSysInfoTable->AcmX2ApicIdValid = SYS_INFO_TABLE_X2APICID_VALID;
}
```
The PSysInfoTable is used by the P-SEAMLDR. To pass the table to P-SEAMLDR, 
later during setting up the VMCS for P-SEAMLDR, the address of the table is 
pointed to by the host FSBASE. 

### Setup VMCS for P-SEAMLDR
```cpp
void SetupVmcs(UINT64 SeamPtBaseAddr) {

    UINT64 VmcsBaseVa = SeamldrData.SeamrrVa + (SeamldrData.PSysInfoTable->PSeamldrRange.Base - SeamldrData.SeamrrBase) + _4KB;
    VmxBasicMsr_u VmxBasic;
    UINT32 PinbasedCtls;
    UINT32 ProcbasedCtls;
    UINT32 ExitCtls;
    UINT32 EntryCtls;
    UINT64 Cr0Fixed0, Cr0Fixed1, Cr0MustBe1;
    UINT64 Cr4Fixed0, Cr4Fixed1, Cr4MustBe1;

    VmxBasic.raw = readMsr64(IA32_VMX_BASIC_MSR_INDEX);

    PinbasedCtls = (UINT32)(readMsr64(IA32_VMX_TRUE_PINBASED_CTLS_MSR_INDEX) & MAX_DWORD);
    ProcbasedCtls = (UINT32)(readMsr64(IA32_VMX_TRUE_PROCBASED_CTLS_MSR_INDEX) & MAX_DWORD);
    ExitCtls = (UINT32)(readMsr64(IA32_VMX_TRUE_EXIT_CTLS_MSR_ADDR) & MAX_DWORD);
    EntryCtls = (UINT32)(readMsr64(IA32_VMX_TRUE_ENTRY_CTLS_MSR_ADDR) & MAX_DWORD);

    Cr0Fixed0 = readMsr64(IA32_VMX_CR0_FIXED0_MSR_INDEX);
    Cr0Fixed1 = readMsr64(IA32_VMX_CR0_FIXED1_MSR_INDEX);
    Cr0MustBe1 = Cr0Fixed1 & Cr0Fixed0;
    Cr4Fixed0 = readMsr64(IA32_VMX_CR4_FIXED0_MSR_INDEX);
    Cr4Fixed1 = readMsr64(IA32_VMX_CR4_FIXED1_MSR_INDEX);
    Cr4MustBe1 = Cr4Fixed1 & Cr4Fixed0;

    Wr_Guest_RIP(VmcsBaseVa, NON_CANONICAL_RIP);
    Wr_Host_CR0(VmcsBaseVa, CR0_PE | CR0_ET | CR0_NE | CR0_WP | CR0_PG | Cr0MustBe1);
    Wr_Host_CR3(VmcsBaseVa, SeamPtBaseAddr);
    Wr_Host_CR4(VmcsBaseVa, CR4_DE | CR4_PAE | CR4_PGE | CR4_OSFXSR | CR4_OSXMMEXCPT | CR4_VMXE | CR4_FSGSBASE | CR4_OSXSAVE | CR4_SMEP | CR4_SMAP | CR4_CET | Cr4MustBe1);
    Wr_Host_CS_Selector(VmcsBaseVa, 8U);
    Wr_Host_SS_Selector(VmcsBaseVa, 0x10U);
    Wr_Host_FS_Selector(VmcsBaseVa, 0x18U);
    Wr_Host_GS_Selector(VmcsBaseVa, 0x18U);
    Wr_Host_TR_Selector(VmcsBaseVa, 0x20U);
    Wr_Host_IA32_PAT(VmcsBaseVa, 0x0006060606060606ULL);
    Wr_Host_IA32_S_Cet(VmcsBaseVa, IA32_CR_S_CET_SH_STK_EN_MASK | IA32_CR_S_CET_ENDBR_EN_MASK | IA32_CR_S_CET_NO_TRACK_EN_MASK);
    Wr_Host_IA32_EFER(VmcsBaseVa, N_IA32_EFER_LMA | LME | N_IA32_EFER_NXE);

    ExitCtls |= (VM_EXIT_CTRL_SAVE_DEBUG_CTRL | VM_EXIT_CTRL_HOST_ADDR_SPACE_SIZE | VM_EXIT_CTRL_SAVE_IA32_PAT | VM_EXIT_CTRL_LOAD_IA32_PAT | \
                 VM_EXIT_CTRL_SAVE_IA32_EFER | VM_EXIT_CTRL_LOAD_IA32_EFER | VM_EXIT_CTRL_CONCEAL_VMX_FROM_PT | VM_EXIT_CTRL_CLEAR_IA32_RTIT_CTL | \
                 VM_EXIT_CTRL_CLEAR_LBR_CTL | VM_EXIT_CTRL_LOAD_CET_HOST_STATE | VM_EXIT_SAVE_IA32_PERF_GLOBAL_CTRL | VM_EXIT_LOAD_IA32_PERF_GLOBAL_CTRL);

    ExitCtls &= ((readMsr64(IA32_VMX_TRUE_EXIT_CTLS_MSR_ADDR) >> 32) & MAX_DWORD);

    Wr_VM_Exit_Control(VmcsBaseVa, ExitCtls);

    EntryCtls |= (VM_ENTRY_CTRL_LOAD_DEBUG_CTRL | VM_ENTRY_CTRL_LOAD_IA32_PERF_GLOBAL_CTRL | VM_ENTRY_CTRL_LOAD_IA32_PAT | VM_ENTRY_CTRL_LOAD_IA32_EFER | \
                  VM_ENTRY_CTRL_CONCEAL_VMX_FROM_PT | VM_ENTRY_CTRL_LOAD_UINV | VM_ENTRY_CTRL_LOAD_IA32_PKRS | \
                  VM_ENTRY_CTRL_LOAD_IA32_RTIT_CTL | VM_ENTRY_CTRL_LOAD_GUEST_CET_STATE | VM_ENTRY_CTRL_LOAD_LBR_CTL);

    EntryCtls &= ((readMsr64(IA32_VMX_TRUE_ENTRY_CTLS_MSR_ADDR) >> 32) & MAX_DWORD);

    Wr_VM_Entry_Control(VmcsBaseVa, EntryCtls);

    Wr_VM_Execution_Control_Pin_Based(VmcsBaseVa, PinbasedCtls);
    Wr_VM_Execution_Control_Proc_Based(VmcsBaseVa, ProcbasedCtls);
   
    Wr_Host_RIP(VmcsBaseVa, (C_CODE_RGN_BASE | SeamldrData.AslrRand) + SeamldrData.PSeamldrConsts->CEntryPointOffset);
    Wr_Host_FS_Base(VmcsBaseVa, C_SYS_INFO_TABLE_BASE | SeamldrData.AslrRand);

    UINT64 HostRSP = (C_STACK_RGN_BASE | SeamldrData.AslrRand) + SeamldrData.PSeamldrConsts->CDataStackSize - 8;
    UINT64 HostSSP = (C_STACK_RGN_BASE | SeamldrData.AslrRand) + SeamldrData.PSeamldrConsts->CDataStackSize + P_SEAMLDR_SHADOW_STACK_SIZE - 8;
    UINT64 HostGSBase = (C_DATA_RGN_BASE | SeamldrData.AslrRand);

    Wr_Host_RSP(VmcsBaseVa, HostRSP);
    Wr_Host_SSP(VmcsBaseVa, HostSSP);
    Wr_Host_GS_Base(VmcsBaseVa, HostGSBase);
    Wr_VMCS_Revision_ID(VmcsBaseVa, (UINT32)VmxBasic.RevisionIdentifier & 0x7FFFFFFF);
```
**The guest state area** is the processor state that is loaded upon VM entry and 
stored on VM exit. **The host state area** is the processor state that is loaded
from the corresponding VMCS components on every VM exit. Regardless of the 
SEAMCALL instructions destination, whether it is P-SEAMLDR or TDX module, it 
implements **VM exit** semantic to enter SEAM mode from legacy VMX. Therefore, 
the host state area is used to set VCPU when the SEAMCALL is invoked. As shown 
in the code above, only the RIP has been set for the guest (for NP-SEAMLDR). 
Also, note that the virtual address mapping of PSysInfoTable for P-SEAMLDR has 
been populated by the MapSysInfoTables function so that P-SEAMLDR can access the 
table through virtual address. 



# P-SEAMLDR
>The Intel P-SEAMLDR module aims to provide interfaces to the VMM, invoked using 
the SEAMCALL instruction, to gain information about Intel TDX, install Intel TDX
modules, and shutdown itself. The installation interface is designed to follow 
the steps below to load or update an Intel TDX module into the MODULE_RANGE:

1. Verify input parameters, including the TDX module's signature structure
(SEAM_SIGSTRUCT).
2. **Load the Intel TDX module image** into the MODULE_RANGE, measure it and 
verify the measurement matches with the signature structure.
3. **Set up data regions, stack regions, and page tables for all logical 
processors.**
4. **Set up SEAM transfer VMCSs** for all logical processors. These VMCSs are 
used by SEAMCALL instructions when an Intel TDX module's API is called, and by the 
SEAMRET instruction when the Intel TDX module API returns.
5. Record the Intel TDX module identity into CPU measurement registers and 
update its load status.
6. Return to VMM using the SEAMRET instruction

### Handoff information from NP-SEAMLDR to P-SEAMLDR
To setup memory region and other configurations for P-SEAMLDR, it requires 
trusted source for hardware reported information.

```cpp
typedef struct PACKED p_sysinfo_table_s
{
    // Fields populated by MCHECK
    uint64_t version;               /**< Structure Version – Set to 0 */
    uint32_t tot_num_lps;           /**< Total number of logical processors in platform */
    uint32_t tot_num_sockets;       /**< Total number of sockets in platform */
    fms_info_t socket_cpuid_table[MAX_PKGS]; /**< List of CPUID.leaf_1.EAX values from all sockets */
    uint64_t p_seamldr_range_base;  /**< Physical base address of P_SEAMLDR_RANGE */
    uint64_t p_seamldr_range_size;  /**< Size of P_SEAMLDR_RANGE, in bytes */
    uint8_t skip_smrr2_check;       /**< When set, indicates that the TDX module should not check SMRR2. */
    uint8_t tdx_ac;                 /**< When set, indicates that TDX memory is protected by Access Control only (no memory integrity). */
    uint8_t reserved_0[62];         /**< Reserved */
    cmr_info_entry_t cmr_data[MAX_CMR]; /**< CMR info (base and size) */
    uint8_t reserved_1[1408];       /**< Reserved */
        
    // Fields populated by NP-SEAMLDR
    uint64_t np_seamldr_mutex;      /**< Mutex used by NP_SEAMLDR to ensure that it’s running on a single package at a time. */
    uint64_t code_rgn_base;         /**< Base address of Code region */
    uint64_t code_rgn_size;         /**< Size of code region in bytes */
    uint64_t data_rgn_base;         /**< Base address of Data region */
    uint64_t data_rgn_size;         /**< Size of data region in bytes */
    uint64_t stack_rgn_base;        /**< Base address of stack region */
    uint64_t stack_rgn_size;        /**< Size of Stack Region in bytes */
    uint64_t keyhole_rgn_base;      /**< Base address of Keyhole region */
    uint64_t keyhole_rgn_size;      /**< Size of the Keyhole region in bytes */
    uint64_t keyhole_edit_rgn_base; /**< Keyhole Edit Region Base */
    uint64_t keyhole_edit_rgn_size; /**< Size of Keyhole Edit Region in bytes */
    uint64_t module_region_base;    /**< Linear base address of SEAM range. */
    uint32_t acm_x2apicid;          /**< The X2APICID of the LP in which the last call to the “shutdown” API should be done (a.k.a. ACM_X2APICID). */
    uint32_t acm_x2apicid_valid;    /**< Whether the ACM_X2APICID field is valid. Must be 1. */
    uint8_t reserved_2[1944];       /**< Reserved */
} p_sysinfo_table_t;
```

This data structure is heavily accessed by the P-SEAMLDR because it provides 
very important information about memory regions of the P-SEAMLDR populated by 
the NP-SEAMLDR. 



```cpp
void pseamldr_dispatcher(void)
{   
    // Must be first thing to do before accessing data or sysinfo table
    pseamldr_data_t* pseamldr_data = init_data_fast_ref_ptrs();
    ......
```

```cpp
// Must be first thing to do before accessing data or sysinfo table
_STATIC_INLINE_ pseamldr_data_t* init_data_fast_ref_ptrs(void)
{                    
    pseamldr_data_t* local_data = calculate_local_data();

    IF_RARE (!local_data->seamldr_data_fast_ref_ptr)
    {
        local_data->seamldr_data_fast_ref_ptr = local_data;
        local_data->psysinfo_fast_ref_ptr = calculate_sysinfo_table();
    }
    
    return local_data;
}   
```

To easily access this table, all SEAMCALL instruction targeting P-SEAMLDR 
invokes pseamldr_dispatcher, which calls init_data_fast_ref_ptrs. 


```cpp
// In SEAM PSEAMLDR module, GSBASE holds a pointer to the local data of current thread
// We are reading GSBASE by loading effective address of 0 with GS prefix
_STATIC_INLINE_ pseamldr_data_t* calculate_local_data(void)
{
    void* local_data_addr;
    _ASM_VOLATILE_ ("rdgsbase %0"
                     :"=r"(local_data_addr)
                     :
                     :"cc");
    
    return (pseamldr_data_t*)local_data_addr;
} 

// In SEAM PSEAMLDR module, FSBASE holds a pointer to the SYSINFO table
// We are reading FSBASE by loading effective address of 0 with FS prefix
_STATIC_INLINE_ p_sysinfo_table_t* calculate_sysinfo_table(void)
{   
    void* sysinfo_table_addr;
    _ASM_VOLATILE_ ("rdfsbase %0"
                     :"=r"(sysinfo_table_addr)
                     :
                     :"cc");

    return (p_sysinfo_table_t*)sysinfo_table_addr;
}
```
PSysInfoTable is located at the last 4KB page of P-SEAMLDR range and populated
by MCHECK and NP-SEAMLDR. However, its corresponding virtual address pointed to
by the FSBASE is already populated in the P-SEAMLDR page table by the NP-SEAMLDR. 
Therefore, the table address can be directly accessible from the P-SEAMLDR side
with virtual address. 

### Overview of P-SEAMLDR Install
SEAMCALL_SEAMLDR_INSTALL leaf function of the SEAMCALL invokes the P-SEAMLDR and 
calls the seamldr_install function inside the P-SEAMLDR. Primary role of this 
function could be summarized as four: 
1. Validates the **VMM passed** parameter, seamldr_params and sigstruct.
2. Initialize page table and set memory region and SYSINFO table for TDX module.
3. Load and verify TDX module.
4. Setup VMCS for TDX Module.

### Keyhole and Page Table for P-SEAMLDR
map_pa_with_memtype ??? What is it.. Cannot understand how the P-SEAMLDR 
maps physical page for itself. 

## Setup page table and other regions for TDX module
Recall that the purpose of the P-SEAMLDR is loading the TDX module, which
includes setting up memory regions and page tables for the module. Before it
populates mappings for memory regions for TDX module, it should configure the 
essential information such as base address and size for each memory region. 


```cpp
    // ******************* Memory initialization *******************
    return_value = initialize_memory_constants(pseamldr_data, &seamldr_params, &pseamldr_data->seam_sigstruct_snapshot, &mem_consts);
```

This function sets up base addresses and size of various memory regions of the 
TDX module based on the all information the P-SEAMLDR have such as sysinfo table
from the NP-SEAMLDR and seamldr_params from host VMM. Also, it checks that the 
TDX memory region is enough to load the TDX module passed from the VMM. 


### Memory map for TDX module
The next step is populating memory mappings for TDX module, not for P-SEAMLDR.
Because all memory regions set inside the initialize_memory_constants function 
reside inside the TDX module's memory, P-SEAMLDR should set up page tables of 
the TDX module not for itself. Note that We have all information in  mem_consts.

```cpp
 // Memory map
    return_value = seam_module_memory_map(pseamldr_data, &mem_consts);
```

```cpp
api_error_type seam_module_memory_map(pseamldr_data_t* pseamldr_data, memory_constants_t* mem_consts)
{
    mem_consts->pml4_physbase = mem_consts->stack_region_physbase - _4KB;
    mem_consts->current_pt_physbase = mem_consts->pml4_physbase - _4KB;

    // Map code range
    if (!map_regular_range(mem_consts, mem_consts->code_region_physbase, mem_consts->code_region_linbase,
                           mem_consts->code_region_size, SEAM_CODE_RANGE_ATTRIBUTES))
    {
        TDX_ERROR("Code range mapping failure\n");
        return PSEAMLDR_ENOMEM;
    }

    // Map data range
    if (!map_regular_range(mem_consts, mem_consts->data_region_physbase, mem_consts->data_region_linbase,
                           mem_consts->data_region_size, SEAM_DATA_RANGE_ATTRIBUTES))
    {
        TDX_ERROR("Data range mapping failure\n");
        return PSEAMLDR_ENOMEM;
    }

    // Data and shadow stack ranges per LP
    for (uint32_t i = 0; i < mem_consts->num_addressable_lps; i++)
    {
        uint64_t stack_pa_start = mem_consts->stack_region_physbase + i * mem_consts->lp_stack_size;
        uint64_t stack_la_start = mem_consts->stack_region_linbase + i * mem_consts->lp_stack_size;

        if (!map_regular_range(mem_consts, stack_pa_start, stack_la_start,
                               mem_consts->data_stack_size, SEAM_DATA_STACK_RANGE_ATTRIBUTES))
        {
            TDX_ERROR("Data stack range mapping failure\n");
            return PSEAMLDR_ENOMEM;
        }

        if (!map_regular_range(mem_consts,
                               stack_pa_start + mem_consts->data_stack_size,
                               stack_la_start + mem_consts->data_stack_size,
                               mem_consts->shadow_stack_size, SEAM_SHADOW_STACK_RANGE_ATTRIBUTES))
        {
            TDX_ERROR("Shadow stack range mapping failure\n");
            return PSEAMLDR_ENOMEM;
        }
    }

    // Sysinfo page
    if (!map_regular_range(mem_consts, pseamldr_data->system_info.seamrr_base, mem_consts->sysinfo_table_linbase,
                           _4KB, SEAM_SYSINFO_RANGE_ATTRIBUTES))
    {
        TDX_ERROR("Sysinfo table mapping failure\n");
        return PSEAMLDR_ENOMEM;
    }

    // Keyhole + keyhole edit pages
    if (!map_keyhole_range(mem_consts))
    {
        TDX_ERROR("Keyholes mapping failure\n");
        FATAL_ERROR();
    }

    return PSEAMLDR_SUCCESS;
}
```

When it comes to the memory mapping function that maps physical addresses, it is
easy to find two different functions map_pa and map_seam_range_page. However, 
they populate mapping on two different page table. map_pa is used for P-SEAMLDR 
and the other is used for TDX module. Note that pml4_physbase is the base page
table for the TDX module, which is the one page before the stack region of the
TDX module. Through the map_regular_range, which invokes the map_seam_range_page,
it generates mapping in the TDX module's page table where the pml4_physbase is 
the root of the page table. 

## Load and Verify TDX Module
```cpp
    // Image load and verify
    return_value = seam_module_load_and_verify(pseamldr_data, p_sysinfo_table,
                             &seamldr_params, &pseamldr_data->seam_sigstruct_snapshot);
```

```cpp
static api_error_type seam_module_load_and_verify(pseamldr_data_t* pseamldr_data, p_sysinfo_table_t* p_sysinfo_table,
                                                  seamldr_params_t* seamldr_params, seam_sigstruct_t* seam_sigstruct)
{
    uint64_t code_region_start_la;

    code_region_start_la = p_sysinfo_table->module_region_base + pseamldr_data->system_info.seamrr_size
                           - p_sysinfo_table->p_seamldr_range_size - SEAMRR_MODULE_CODE_REGION_SIZE;

    // Copy and measure SEAM module image pages to the last 2M of the SEAM range
    for (uint64_t i = 0; i < seamldr_params->num_module_pages; i++)
    {
        void* src_page_la = map_pa((void*)seamldr_params->mod_pages_pa_list[i], TDX_RANGE_RO);
        void* dst_page_la = (void*)(code_region_start_la + (i * SEAM_MODULE_PAGE_SIZE));
        pseamldr_memcpy(dst_page_la, SEAM_MODULE_PAGE_SIZE, src_page_la, SEAM_MODULE_PAGE_SIZE);
        free_la(src_page_la);
    }

    // Measure the image (in SEAM range) using SHA-384.
    // If the result is not equal to TMP_SIGSTRUCT.SEAMHASH then set ERROR_CODE = EBADHASH.
    uint32_t module_size = (uint32_t)(seamldr_params->num_module_pages * SEAM_MODULE_PAGE_SIZE);
    IF_RARE (!compute_and_verify_hash((const uint8_t*)code_region_start_la, module_size, seam_sigstruct->seamhash))
    {
        TDX_ERROR("Incorrect SEAM module hash!\n");
        return PSEAMLDR_EBADHASH;
    }

    return PSEAMLDR_SUCCESS;
}

```

It also measures the has value of the TDX module and reject loading when the 
hash does not match with the pre-calculated value stored in the sigstruct for 
TDX module. 


### Update memory map after loading
```cpp
static void setup_system_information(p_sysinfo_table_t* p_sysinfo_table, memory_constants_t* mem_consts)
{   
    // Copy MCHECK information from P_SYS_INFO_TABLE to SYS_INFO_TABLE
    sysinfo_table_t* sysinfo_table = (sysinfo_table_t*)p_sysinfo_table->module_region_base;
    
    pseamldr_memcpy(sysinfo_table, SYSINFO_TABLE_MCHECK_DATA_SIZE, p_sysinfo_table, SYSINFO_TABLE_MCHECK_DATA_SIZE);
    
    sysinfo_table->code_rgn_base = mem_consts->code_region_linbase;
    sysinfo_table->code_rgn_size = mem_consts->code_region_size;
    sysinfo_table->data_rgn_base = mem_consts->data_region_linbase;
    sysinfo_table->data_rgn_size = mem_consts->data_region_size;
    sysinfo_table->stack_rgn_base = mem_consts->stack_region_linbase;
    sysinfo_table->stack_rgn_size = mem_consts->stack_region_size;
    sysinfo_table->keyhole_rgn_base = mem_consts->keyhole_region_linbase;
    sysinfo_table->keyhole_rgn_size = mem_consts->keyhole_region_size;
    sysinfo_table->keyhole_edit_rgn_base = mem_consts->keyedit_region_linbase;
    sysinfo_table->keyhole_edit_rgn_size = mem_consts->keyedit_region_size;
    sysinfo_table->num_stack_pages = (mem_consts->data_stack_size / _4KB) - 1;
    sysinfo_table->num_tls_pages = (mem_consts->local_data_size / _4KB) - 1;
}   
```

After the TDX module has been loaded to the memory, the memory map in the 
sysinfo table should be updated because the sysinfo table is also passed to the 
TDX module as P-SEAMLDR received it from NP-SEAMLDR. This table is accessible 
by the TDX module through FSBASE. 

## Setup VMCS for TDX Module 
One of its important role is
setting the VMCS structure associated with seam loader (refer to setup_seam_vmcs).

```cpp
    // SEAM VMCS setup
    setup_seam_vmcs(p_sysinfo_table->module_region_base + _4KB, &mem_consts, pseamldr_data->seam_sigstruct_snapshot.rip_offset);
```

```cpp
void setup_seam_vmcs(uint64_t vmcs_la_base, memory_constants_t* mem_consts, uint64_t rip_offset)
{
    ia32_vmx_basic_t vmx_basic;
    uint32_t pinbased_ctls, procbased_ctls, exit_ctls, entry_ctls;
    uint64_t cr0_fixed0, cr0_fixed1, cr0_mustbe1;
    uint64_t cr4_fixed0, cr4_fixed1, cr4_mustbe1;

    vmx_basic.raw = ia32_rdmsr(IA32_VMX_BASIC_MSR_ADDR);

    pinbased_ctls = (uint32_t)(ia32_rdmsr(IA32_VMX_TRUE_PINBASED_CTLS_MSR_ADDR) & BIT_MASK_32BITS);
    procbased_ctls = (uint32_t)(ia32_rdmsr(IA32_VMX_TRUE_PROCBASED_CTLS_MSR_ADDR) & BIT_MASK_32BITS);
    exit_ctls = (uint32_t)(ia32_rdmsr(IA32_VMX_TRUE_EXIT_CTLS_MSR_ADDR) & BIT_MASK_32BITS);
    entry_ctls = (uint32_t)(ia32_rdmsr(IA32_VMX_TRUE_ENTRY_CTLS_MSR_ADDR) & BIT_MASK_32BITS);

    cr0_fixed0 = ia32_rdmsr(IA32_VMX_CR0_FIXED0_MSR_ADDR);
    cr0_fixed1 = ia32_rdmsr(IA32_VMX_CR0_FIXED1_MSR_ADDR);
    cr0_mustbe1 = cr0_fixed1 & cr0_fixed0;
    cr4_fixed0 = ia32_rdmsr(IA32_VMX_CR4_FIXED0_MSR_ADDR);
    cr4_fixed1 = ia32_rdmsr(IA32_VMX_CR4_FIXED1_MSR_ADDR);
    cr4_mustbe1 = cr4_fixed1 & cr4_fixed0;

    wr_guest_rip(vmcs_la_base, SEAM_VMCS_NON_CANONICAL_RIP);
    wr_host_cr0(vmcs_la_base, SEAM_VMCS_CR0_BITS | cr0_mustbe1);
    wr_gost_cr3(vmcs_la_base, mem_consts->pml4_physbase);
    wr_host_cr4(vmcs_la_base, SEAM_VMCS_CR4_BITS | cr4_mustbe1);
    wr_host_cs_selector(vmcs_la_base, SEAM_VMCS_CS_SELECTOR);
    wr_host_ss_selector(vmcs_la_base, SEAM_VMCS_SS_SELECTOR);
    wr_host_fs_selector(vmcs_la_base, SEAM_VMCS_FS_SELECTOR);
    wr_host_gs_selector(vmcs_la_base, SEAM_VMCS_GS_SELECTOR);
    wr_host_tr_selector(vmcs_la_base, SEAM_VMCS_TR_SELECTOR);
    wr_host_ia32_pat(vmcs_la_base, SEAM_VMCS_PAT_MSR_VALUE);
    wr_host_ia32_s_cet(vmcs_la_base, SEAM_VMCS_S_CET_MSR_VALUE);
    wr_host_ia32_efer(vmcs_la_base, SEAM_VMCS_EFER_MSR_VALUE);

    exit_ctls |= SEAM_VMCS_EXIT_CTLS_VALUE;
    exit_ctls &= ((ia32_rdmsr(IA32_VMX_TRUE_EXIT_CTLS_MSR_ADDR) >> 32) & BIT_MASK_32BITS);

    wr_vm_exit_control(vmcs_la_base, exit_ctls);

    entry_ctls |= SEAM_VMCS_ENTRY_CTLS_VALUE;

    entry_ctls &= ((ia32_rdmsr(IA32_VMX_TRUE_ENTRY_CTLS_MSR_ADDR) >> 32) & BIT_MASK_32BITS);

    wr_vm_entry_control(vmcs_la_base, entry_ctls);

    wr_vm_execution_control_pin_based(vmcs_la_base, pinbased_ctls);
    wr_vm_execution_control_proc_based(vmcs_la_base, procbased_ctls);

    wr_host_rip(vmcs_la_base, mem_consts->code_region_linbase + rip_offset);
    wr_host_fs_base(vmcs_la_base, mem_consts->sysinfo_table_linbase);

    uint64_t host_rsp_first_lp = mem_consts->stack_region_linbase + mem_consts->data_stack_size - 8;
    uint64_t host_ssp_first_lp = mem_consts->stack_region_linbase + mem_consts->lp_stack_size - 8;
    uint64_t host_gsbase_first_lp = mem_consts->data_region_linbase;

    wr_host_rsp(vmcs_la_base, host_rsp_first_lp);
    wr_host_ssp(vmcs_la_base, host_ssp_first_lp);
    wr_host_gs_base(vmcs_la_base, host_gsbase_first_lp);
    wr_vmcs_revision_id(vmcs_la_base, vmx_basic.vmcs_revision_id);

    uint64_t vmcs_size = vmx_basic.vmcs_region_size;

    for (uint64_t i = 1; i < mem_consts->num_addressable_lps; i++)
    {
        uint64_t current_vmcs_la = vmcs_la_base + (i * PAGE_SIZE_IN_BYTES);
        pseamldr_memcpy((void*)current_vmcs_la, vmcs_size, (void*)vmcs_la_base, vmcs_size);
        wr_host_rsp(current_vmcs_la, host_rsp_first_lp + (i * mem_consts->lp_stack_size));
        wr_host_ssp(current_vmcs_la, host_ssp_first_lp + (i * mem_consts->lp_stack_size));
        wr_host_gs_base(current_vmcs_la, host_gsbase_first_lp + (i* mem_consts->local_data_size));
    }
}
```

The VMCS for TDX module has been set in very similar context as with VMCS for 
P-SEAMLDR. FSBASE and GSBASE are used to pass information from the P-SEAMLDR to
TDX module and the root page table, pml4_physbase, is set as the CR3 of the host,
which is the TDX module. Also all the required mapping to run the TDX module are
ready so the CPU can run the TDX module code and access data right after it 
jumps to the TDX module through SEAMCALL. One major difference of VMCS for TDX
module compared with the VMCS for P-SEAMLDR is that it requires VMCS **per 
logical processor**. Therefore, the last for loop above code sets up different 
memory area per core. 


[TXT]: https://en.wikipedia.org/wiki/Trusted_Execution_Technology
[VMCS]: https://revers.engineering/day-3-multiprocessor-initialization-error-handling-the-vmcs/
