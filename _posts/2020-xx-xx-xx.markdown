---
layout: post
titile: "Microops in GEM5"
categories: GEM5, Microops
---
430     def defineMicroLoadOp(mnemonic, code, bigCode='',
431                           mem_flags="0", big=True, nonSpec=False,
432                           implicitStack=False):
433         global header_output
434         global decoder_output
435         global exec_output
436         global microopClasses
437         Name = mnemonic
438         name = mnemonic.lower()
439
440         # Build up the all register version of this micro op
441         iops = [InstObjParams(name, Name, 'X86ISA::LdStOp',
442                               { "code": code,
443                                 "ea_code": calculateEA,
444                                 "memDataSize": "dataSize" })]
445         if big:
446             iops += [InstObjParams(name, Name + "Big", 'X86ISA::LdStOp',
447                                    { "code": bigCode,
448                                      "ea_code": calculateEA,
449                                      "memDataSize": "dataSize" })]
450         for iop in iops:
451             header_output += MicroLdStOpDeclare.subst(iop)
452             decoder_output += MicroLdStOpConstructor.subst(iop)
453             exec_output += MicroLoadExecute.subst(iop)
454             exec_output += MicroLoadInitiateAcc.subst(iop)
455             exec_output += MicroLoadCompleteAcc.subst(iop)
456
457         if implicitStack:
458             # For instructions that implicitly access the stack, the address
459             # size is the same as the stack segment pointer size, not the
460             # address size if specified by the instruction prefix
461             addressSize = "env.stackSize"
462         else:
463             addressSize = "env.addressSize"
464
465         base = LdStOp
466         if big:
467             base = BigLdStOp
468         class LoadOp(base):
469             def __init__(self, data, segment, addr, disp = 0,
470                     dataSize="env.dataSize",
471                     addressSize=addressSize,
472                     atCPL0=False, prefetch=False, nonSpec=nonSpec,
473                     implicitStack=implicitStack, uncacheable=False):
474                 super(LoadOp, self).__init__(data, segment, addr,
475                         disp, dataSize, addressSize, mem_flags,
476                         atCPL0, prefetch, nonSpec, implicitStack, uncacheable)
477                 self.className = Name
478                 self.mnemonic = name
479
480         microopClasses[name] = LoadOp


222 def template MicroLdStOpDeclare {{
223     class %(class_name)s : public %(base_class)s
224     {
225       public:
226         %(class_name)s(ExtMachInst _machInst,
227                 const char * instMnem, uint64_t setFlags,
228                 uint8_t _scale, InstRegIndex _index, InstRegIndex _base,
229                 uint64_t _disp, InstRegIndex _segment,
230                 InstRegIndex _data,
231                 uint8_t _dataSize, uint8_t _addressSize,
232                 Request::FlagsType _memFlags);
233
234         Fault execute(ExecContext *, Trace::InstRecord *) const;
235         Fault initiateAcc(ExecContext *, Trace::InstRecord *) const;
236         Fault completeAcc(PacketPtr, ExecContext *, Trace::InstRecord *) const;
237     };
238 }};

*decoder-ns.hh.inc*
```cpp
3585     class Ld : public X86ISA::LdStOp
3586     {
3587       public:
3588         Ld(ExtMachInst _machInst,
3589                 const char * instMnem, uint64_t setFlags,
3590                 uint8_t _scale, InstRegIndex _index, InstRegIndex _base,
3591                 uint64_t _disp, InstRegIndex _segment,
3592                 InstRegIndex _data,
3593                 uint8_t _dataSize, uint8_t _addressSize,
3594                 Request::FlagsType _memFlags);
3595
3596         Fault execute(ExecContext *, Trace::InstRecord *) const;
3597         Fault initiateAcc(ExecContext *, Trace::InstRecord *) const;
3598         Fault completeAcc(PacketPtr, ExecContext *, Trace::InstRecord *) const;
3599     };
```


260 def template MicroLdStOpConstructor {{
261     %(class_name)s::%(class_name)s(
262             ExtMachInst machInst, const char * instMnem, uint64_t setFlags,
263             uint8_t _scale, InstRegIndex _index, InstRegIndex _base,
264             uint64_t _disp, InstRegIndex _segment,
265             InstRegIndex _data,
266             uint8_t _dataSize, uint8_t _addressSize,
267             Request::FlagsType _memFlags) :
268         %(base_class)s(machInst, "%(mnemonic)s", instMnem, setFlags,
269                 _scale, _index, _base,
270                 _disp, _segment, _data,
271                 _dataSize, _addressSize, _memFlags, %(op_class)s)
272     {
273         %(constructor)s;
274     }
275 }};

*decoder-ns.cc.inc*
```cpp
10488     Ld::Ld(
10489             ExtMachInst machInst, const char * instMnem, uint64_t setFlags,
10490             uint8_t _scale, InstRegIndex _index, InstRegIndex _base,
10491             uint64_t _disp, InstRegIndex _segment,
10492             InstRegIndex _data,
10493             uint8_t _dataSize, uint8_t _addressSize,
10494             Request::FlagsType _memFlags) :
10495         X86ISA::LdStOp(machInst, "ld", instMnem, setFlags,
10496                 _scale, _index, _base,
10497                 _disp, _segment, _data,
10498                 _dataSize, _addressSize, _memFlags, MemReadOp)
10499     {
10500
10501         _numSrcRegs = 0;
10502         _numDestRegs = 0;
10503         _numFPDestRegs = 0;
10504         _numVecDestRegs = 0;
10505         _numVecElemDestRegs = 0;
10506         _numVecPredDestRegs = 0;
10507         _numIntDestRegs = 0;
10508         _numCCDestRegs = 0;
10509         _srcRegIdx[_numSrcRegs++] = RegId(IntRegClass, INTREG_FOLDED(index, foldABit));
10510         _srcRegIdx[_numSrcRegs++] = RegId(IntRegClass, INTREG_FOLDED(base, foldABit));
10511         _srcRegIdx[_numSrcRegs++] = RegId(IntRegClass, INTREG_FOLDED(data, foldOBit));
10512         _destRegIdx[_numDestRegs++] = RegId(IntRegClass, INTREG_FOLDED(data, foldOBit));
10513         _numIntDestRegs++;
10514         _srcRegIdx[_numSrcRegs++] = RegId(MiscRegClass, MISCREG_SEG_EFF_BASE(segment));
10515         flags[IsInteger] = true;
10516         flags[IsLoad] = true;
10517         flags[IsMemRef] = true;;
10518     }
```




 90 def template MicroLoadExecute {{
 91     Fault %(class_name)s::execute(ExecContext *xc,
 92           Trace::InstRecord *traceData) const
 93     {
 94         Fault fault = NoFault;
 95         Addr EA;
 96
 97         %(op_decl)s;
 98         %(op_rd)s;
 99         %(ea_code)s;
100         DPRINTF(X86, "%s : %s: The address is %#x\n", instMnem, mnemonic, EA);
101
102         fault = readMemAtomic(xc, traceData, EA, Mem, dataSize, memFlags);
103
104         if (fault == NoFault) {
105             %(code)s;
106         } else if (memFlags & Request::PREFETCH) {
107             // For prefetches, ignore any faults/exceptions.
108             return NoFault;
109         }
110         if(fault == NoFault)
111         {
112             %(op_wb)s;
113         }
114
115         return fault;
116     }
117 }};


*exec-ns.cc.inc*
```cpp
19101     Fault Ld::execute(ExecContext *xc,
19102           Trace::InstRecord *traceData) const
19103     {
19104         Fault fault = NoFault;
19105         Addr EA;
19106
19107         uint64_t Index = 0;
19108 uint64_t Base = 0;
19109 uint64_t Data = 0;
19110 uint64_t SegBase = 0;
19111 uint64_t Mem;
19112 ;
19113         Index = xc->readIntRegOperand(this, 0);
19114 Base = xc->readIntRegOperand(this, 1);
19115 Data = xc->readIntRegOperand(this, 2);
19116 SegBase = xc->readMiscRegOperand(this, 3);
19117 ;
19118         EA = SegBase + bits(scale * Index + Base + disp, addressSize * 8 - 1, 0);;
19119         DPRINTF(X86, "%s : %s: The address is %#x\n", instMnem, mnemonic, EA);
19120
19121         fault = readMemAtomic(xc, traceData, EA, Mem, dataSize, memFlags);
19122
19123         if (fault == NoFault) {
19124             Data = merge(Data, Mem, dataSize);;
19125         } else if (memFlags & Request::PREFETCH) {
19126             // For prefetches, ignore any faults/exceptions.
19127             return NoFault;
19128         }
19129         if(fault == NoFault)
19130         {
19131
19132
19133         {
19134             uint64_t final_val = Data;
19135             xc->setIntRegOperand(this, 0, final_val);
19136
19137             if (traceData) { traceData->setData(final_val); }
19138         };
19139         }
19140
19141         return fault;
19142     }
```

As shown in the above code, 
defineMicroLoadOp method generates each microop implementation.
However, we don't know how the microop instruction assembly are translated to 
actual microcode implementation invocation.

17353     const MicroPC X86ISA::MicrocodeRom::numMicroops = 209;
17354
17355     X86ISA::MicrocodeRom::MicrocodeRom()
17356     {
17357         using namespace RomLabels;
17358         genFuncs = new GenFunc[numMicroops];
17359         genFuncs[0] = generate_Sll_0;
17360 genFuncs[1] = generate_Ld_1;
17361 genFuncs[2] = generate_Ld_2;
17362 genFuncs[3] = generate_Chks_3;
17363 genFuncs[4] = generate_Srl_4;
17364 genFuncs[5] = generate_And_5;
17365 genFuncs[6] = generate_AndFlags_6;
17366 genFuncs[7] = generate_MicroBranchFlags_7;
17367 genFuncs[8] = generate_Ld_8;
17368 genFuncs[9] = generate_MicroBranch_9;
17369 genFuncs[10] = generate_Ld_10;
17370 genFuncs[11] = generate_Chks_11;
17371 genFuncs[12] = generate_Wrdl_12;
17372 genFuncs[13] = generate_Wrdh_13;

15375             StaticInstPtr
15376             generate_Ld_123(StaticInstPtr curMacroop)
15377             {
15378                 static const char *macrocodeBlock = romMnemonic;
15379                 static ExtMachInst dummyExtMachInst;
15380                 static const EmulEnv dummyEmulEnv(0, 0, 1, 1, 1);
15381                 Macroop * macroop = dynamic_cast<Macroop *>(curMacroop.get());
15382                 const ExtMachInst &machInst =
15383                     macroop ? macroop->getExtMachInst() : dummyExtMachInst;
15384                 const EmulEnv &env =
15385                     macroop ? macroop->getEmulEnv() : dummyEmulEnv;
15386                 // env may not be used in the microop's constructor.
15387                 InstRegIndex reg(env.reg);
15388                 reg = reg;
15389                 using namespace RomLabels;
15390                 return
15391                 (8 >= 4) ?
15392                     (StaticInstPtr)(new LdBig(machInst,
15393                         macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsDelayedCommit), 1, InstRegIndex(NUM_INTREGS+0),
15394                         InstRegIndex(NUM_INTREGS+4), 8, InstRegIndex(SYS_SEGMENT_REG_IDTR), InstRegIndex(NUM_INTREGS+2),
15395                         8, 8, 0 | (CPL0FlagBit << FlagShift) | (machInst.legacy.addr ? (AddrSizeFlagBit << FlagShift) : 0))) :
15396                     (StaticInstPtr)(new Ld(machInst,
15397                         macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsDelayedCommit), 1, InstRegIndex(NUM_INTREGS+0),
15398                         InstRegIndex(NUM_INTREGS+4), 8, InstRegIndex(SYS_SEGMENT_REG_IDTR), InstRegIndex(NUM_INTREGS+2),
15399                         8, 8, 0 | (CPL0FlagBit << FlagShift) | (machInst.legacy.addr ? (AddrSizeFlagBit << FlagShift) : 0)))
15400             ;
15401             }
15402
15403             StaticInstPtr
15404             generate_Ld_124(StaticInstPtr curMacroop)
15405             {
15406                 static const char *macrocodeBlock = romMnemonic;
15407                 static ExtMachInst dummyExtMachInst;
15408                 static const EmulEnv dummyEmulEnv(0, 0, 1, 1, 1);
15409                 Macroop * macroop = dynamic_cast<Macroop *>(curMacroop.get());
15410                 const ExtMachInst &machInst =
15411                     macroop ? macroop->getExtMachInst() : dummyExtMachInst;
15412                 const EmulEnv &env =
15413                     macroop ? macroop->getEmulEnv() : dummyEmulEnv;
15414                 // env may not be used in the microop's constructor.
15415                 InstRegIndex reg(env.reg);
15416                 reg = reg;
15417                 using namespace RomLabels;
15418                 return
15419                 (8 >= 4) ?
15420                     (StaticInstPtr)(new LdBig(machInst,
15421                         macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsDelayedCommit), 1, InstRegIndex(NUM_INTREGS+0),
15422                         InstRegIndex(NUM_INTREGS+4), 0, InstRegIndex(SYS_SEGMENT_REG_IDTR), InstRegIndex(NUM_INTREGS+4),
15423                         8, 8, 0 | (CPL0FlagBit << FlagShift) | (machInst.legacy.addr ? (AddrSizeFlagBit << FlagShift) : 0))) :
15424                     (StaticInstPtr)(new Ld(machInst,
15425                         macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsDelayedCommit), 1, InstRegIndex(NUM_INTREGS+0),
15426                         InstRegIndex(NUM_INTREGS+4), 0, InstRegIndex(SYS_SEGMENT_REG_IDTR), InstRegIndex(NUM_INTREGS+4),
15427                         8, 8, 0 | (CPL0FlagBit << FlagShift) | (machInst.legacy.addr ? (AddrSizeFlagBit << FlagShift) : 0)))
15428             ;
15429             }
