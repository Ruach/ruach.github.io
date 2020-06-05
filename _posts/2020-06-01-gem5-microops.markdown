---
layout: post
titile: "Microops in GEM5"
categories: GEM5, Microops
---
*src/arch/x86/isa/decoder/x87/isa*
```
format WarnUnimpl {
    0x1B: decode OPCODE_OP_BOTTOM3 {
        0x0: decode MODRM_REG {
            0x0: decode MODRM_MOD {
                0x3: Inst::FADD1(Eq);
                // 32-bit memory operand
                default: Inst::FADD1(Md);
            }
            0x1: decode MODRM_MOD {
                0x3: Inst::FMUL1(Eq);
                default: Inst::FMUL1(Md);
            }
            0x2: fcom();
            0x3: fcomp();
            0x4: decode MODRM_MOD {
                0x3: Inst::FSUB1(Eq);
                default: Inst::FSUB1(Md);
            }
```

*gem5/build/X86/arch/x86/generated/decode-method.cc.inc*
```cpp
                    case 0x4:
                      switch (MODRM_MOD) {

                        case 0x3:
                          // Inst::FSUB1((['Eq'], {}))
                          switch(MODRM_MOD) {
                                case 3: return new X86Macroop::FSUB1_R(machInst, EmulEnv((MODRM_RM | (REX_B << 3)),
                                                        0,
                                                        8,
                                                        ADDRSIZE,
                                                        STACKSIZE));

                                default:
                                  if(machInst.modRM.mod == 0 &&
                                    machInst.modRM.rm == 5 &&
                                    machInst.mode.submode == SixtyFourBitMode)
                                  { return new X86Macroop::FSUB1_P(machInst, EmulEnv(0,
                                                        0,
                                                        8,
                                                        ADDRSIZE,
                                                        STACKSIZE));
                                  }
                                  else
                                  { return new X86Macroop::FSUB1_M(machInst, EmulEnv(0,
                                                        0,
                                                        8,
                                                        ADDRSIZE,
                                                        STACKSIZE));
                                  }
                          }
                          break;

                        default:
                          // Inst::FSUB1((['Md'], {}))
                          switch(MODRM_MOD) {
                                case 3:
                                  return new Unknown(machInst);

                                default:
                                  if(machInst.modRM.mod == 0 &&
                                    machInst.modRM.rm == 5 &&
                                    machInst.mode.submode == SixtyFourBitMode)
                                  { return new X86Macroop::FSUB1_P(machInst, EmulEnv(0,
                                                        0,
                                                        4,
                                                        ADDRSIZE,
                                                        STACKSIZE));
                           }
                                  else
                                  { return new X86Macroop::FSUB1_M(machInst, EmulEnv(0,
                                                        0,
                                                        4,
                                                        ADDRSIZE,
                                                        STACKSIZE));
                           }
                          }
                          break;
                        }
                      M5_UNREACHABLE;

```


*/src/arch/x86/isa/x87/arithmetic/subtraction.py*
```
def macroop FSUB1_R
{
    subfp st(0), st(0), sti
};
def macroop FSUB1_M
{
    ldfp ufp1, seg, sib, disp
    subfp st(0), st(0), ufp1
};

def macroop FSUB1_P
{
    rdip t7
    ldfp ufp1, seg, riprel, disp
    subfp st(0), st(0), ufp1
};
```

*/gem5/build/X86/arch/x86/generated/decoder-ns.cc.inc*

```cpp
// Inst::FSUB1((['Eq'], {}))

        X86Macroop::FSUB1_R::FSUB1_R(
                ExtMachInst machInst, EmulEnv _env)
            : Macroop("fsub1", machInst, 1, _env)
        {
            ;

                uint64_t adjustedImm = IMMEDIATE;
                //This is to pacify gcc in case the immediate isn't used.
                adjustedImm = adjustedImm;
            ;

                uint64_t adjustedDisp = DISPLACEMENT;
                //This is to pacify gcc in case the displacement isn't used.
                adjustedDisp = adjustedDisp;
            ;
            env.setSeg(machInst);
;

        _numSrcRegs = 0;
        _numDestRegs = 0;
        _numFPDestRegs = 0;
        _numVecDestRegs = 0;
        _numVecElemDestRegs = 0;
        _numVecPredDestRegs = 0;
        _numIntDestRegs = 0;
        _numCCDestRegs = 0;;
            const char *macrocodeBlock = "FSUB1_R";
            //alloc_microops is the code that sets up the microops
            //array in the parent class.
            microops[0] = new subfp(machInst, macrocodeBlock,
                    (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsFirstMicroop) | (1ULL << StaticInst::IsLastMicroop), InstRegIndex(NUM_FLOATREGS + (((0) + 8) % 8)), InstRegIndex(NUM_FLOATREGS + (((env.reg) + 8) % 8)), InstRegIndex(NUM_FLOATREGS + (((0) + 8) % 8)),
                    env.dataSize, 0);
;
        }

    std::string
    X86Macroop::FSUB1_R::generateDisassembly(Addr pc,
            const SymbolTable *symtab) const
    {
        std::stringstream out;
        out << mnemonic << "\t";

        int regSize = (false || (env.base == INTREG_RSP && false) ?
                         env.stackSize :
                         env.dataSize);
        printReg(out, InstRegIndex((MODRM_RM | (REX_B << 3))), regSize);

        // Shut up gcc.
        regSize = regSize;
        return out.str();
    }

```


```python
class X86Microop(object):

    generatorNameTemplate = "generate_%s_%d"

    generatorTemplate = '''
        StaticInstPtr
        ''' + generatorNameTemplate + '''(StaticInstPtr curMacroop)
        {
            static const char *macrocodeBlock = romMnemonic;
            static ExtMachInst dummyExtMachInst;
            static const EmulEnv dummyEmulEnv(0, 0, 1, 1, 1);

            Macroop * macroop = dynamic_cast<Macroop *>(curMacroop.get());
            const ExtMachInst &machInst =
                macroop ? macroop->getExtMachInst() : dummyExtMachInst;
            const EmulEnv &env =
                macroop ? macroop->getEmulEnv() : dummyEmulEnv;
            // env may not be used in the microop's constructor.
            InstRegIndex reg(env.reg);
            reg = reg;
            using namespace RomLabels;
            return %s;
        }
    '''

    def __init__(self, name):
        self.name = name

    def microFlagsText(self, flags):
        wrapped = ("(1ULL << StaticInst::%s)" % flag for flag in flags)
        return " | ".join(wrapped)

    def getGeneratorDef(self, micropc):
        return self.generatorTemplate % \
            (self.className, micropc, \
             self.getAllocator(["IsMicroop", "IsDelayedCommit"]))

    def getGenerator(self, micropc):
        return self.generatorNameTemplate % (self.className, micropc)

```

```python
class FpOpMeta(type):
    def buildCppClasses(self, name, Name, suffix, \
            code, flag_code, cond_check, else_code, op_class):

        # Globals to stick the output in
        global header_output
        global decoder_output
        global exec_output

        # Stick all the code together so it can be searched at once
        allCode = "|".join((code, flag_code, cond_check, else_code))

        # If there's something optional to do with flags, generate
        # a version without it and fix up this version to use it.
        if flag_code is not "" or cond_check is not "true":
            self.buildCppClasses(name, Name, suffix,
                    code, "", "true", else_code, op_class)
            suffix = "Flags" + suffix

        base = "X86ISA::FpOp"

        # Get everything ready for the substitution
        iop_tag = InstObjParams(name, Name + suffix + "TopTag", base,
                {"code" : code,
                 "flag_code" : flag_code,
                 "cond_check" : cond_check,
                 "else_code" : else_code,
                 "tag_code" : "FTW = genX87Tags(FTW, TOP, spm);",
                 "top_code" : "TOP = (TOP + spm + 8) % 8;",
                 "op_class" : op_class})
        iop_top = InstObjParams(name, Name + suffix + "Top", base,
                {"code" : code,
                 "flag_code" : flag_code,
                 "cond_check" : cond_check,
                 "else_code" : else_code,
                 "tag_code" : ";",
                 "top_code" : "TOP = (TOP + spm + 8) % 8;",
                 "op_class" : op_class})
        iop = InstObjParams(name, Name + suffix, base,
                {"code" : code,
                 "flag_code" : flag_code,
                 "cond_check" : cond_check,
                 "else_code" : else_code,
                 "tag_code" : ";",
                 "top_code" : ";",
                 "op_class" : op_class})

        # Generate the actual code (finally!)
        header_output += MicroFpOpDeclare.subst(iop_tag)
        decoder_output += MicroFpOpConstructor.subst(iop_tag)
        exec_output += MicroFpOpExecute.subst(iop_tag)
        header_output += MicroFpOpDeclare.subst(iop_top)
        decoder_output += MicroFpOpConstructor.subst(iop_top)
        exec_output += MicroFpOpExecute.subst(iop_top)
        header_output += MicroFpOpDeclare.subst(iop)
        decoder_output += MicroFpOpConstructor.subst(iop)
        exec_output += MicroFpOpExecute.subst(iop)


    def __new__(mcls, Name, bases, dict):
        abstract = False
        name = Name.lower()
        if "abstract" in dict:
            abstract = dict['abstract']
            del dict['abstract']

        cls = super(FpOpMeta, mcls).__new__(mcls, Name, bases, dict)
        if not abstract:
            cls.className = Name
            cls.mnemonic = name
            code = cls.code
            flag_code = cls.flag_code
            cond_check = cls.cond_check
            else_code = cls.else_code
            op_class = cls.op_class

            # Set up the C++ classes
            mcls.buildCppClasses(cls, name, Name, "",
                    code, flag_code, cond_check, else_code, op_class)

            # Hook into the microassembler dict
            global microopClasses
            microopClasses[name] = cls
        return cls


class FpBinaryOp(X86Microop):
    __metaclass__ = FpOpMeta
    # This class itself doesn't act as a microop
    abstract = True

    # Default template parameter values
    flag_code = ""
    cond_check = "true"
    else_code = ";"
    op_class = "FloatAddOp"

    def __init__(self, dest, src1, src2, spm=0, \
            SetStatus=False, UpdateFTW=True, dataSize="env.dataSize"):
        self.dest = dest
        self.src1 = src1
        self.src2 = src2
        self.spm = spm
        self.dataSize = dataSize
        if SetStatus:
            self.className += "Flags"
        if spm:
            self.className += "Top"
        if spm and UpdateFTW:
            self.className += "Tag"

    def getAllocator(self, microFlags):
        return '''new %(class_name)s(machInst, macrocodeBlock,
                %(flags)s, %(src1)s, %(src2)s, %(dest)s,
                %(dataSize)s, %(spm)d)''' % {
            "class_name" : self.className,
            "flags" : self.microFlagsText(microFlags),
            "src1" : self.src1, "src2" : self.src2,
            "dest" : self.dest,
            "dataSize" : self.dataSize,
            "spm" : self.spm}

class subfp(FpBinaryOp):
    code = 'FpDestReg = FpSrcReg1 - FpSrcReg2;'

```







