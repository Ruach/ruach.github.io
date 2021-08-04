---
layout: post
titile: "Microops in GEM5"
categories: GEM5, Microops
---
As we've seen in the macroop to microop parsing,
each microop invocation in macrocode definition
can be interpreted python class
associated with that microop.
From the retrieved python microop,
it can further retrieve automatically generated CPP classes
that are instantiated by CPP macroop class.

In this posting, we will take a look at the *limm microop* as an example.
When you open the isa file in the microops,
you can find that there exists two categories of blocks:
template and let block.
Let's try to look at what are those blocks one by one

## Let blocks: define python class and generate CPP class for microop
*gem5/src/arch/x86/isa/microops/limmop.isa*
```python
{% raw %}
105 let {{
106     class LimmOp(X86Microop):
107         def __init__(self, dest, imm, dataSize="env.dataSize"):
108             self.className = "Limm"
109             self.mnemonic = "limm"
110             self.dest = dest
111             if isinstance(imm, (int, long)):
112                 imm = "ULL(%d)" % imm
113             self.imm = imm
114             self.dataSize = dataSize
115
116         def getAllocator(self, microFlags):
117             allocString = '''
118                 (%(dataSize)s >= 4) ?
119                     (StaticInstPtr)(new %(class_name)sBig(machInst,
120                         macrocodeBlock, %(flags)s, %(dest)s, %(imm)s,
121                         %(dataSize)s)) :
122                     (StaticInstPtr)(new %(class_name)s(machInst,
123                         macrocodeBlock, %(flags)s, %(dest)s, %(imm)s,
124                         %(dataSize)s))
125             '''
126             allocator = allocString % {
127                 "class_name" : self.className,
128                 "mnemonic" : self.mnemonic,
129                 "flags" : self.microFlagsText(microFlags),
130                 "dest" : self.dest, "imm" : self.imm,
131                 "dataSize" : self.dataSize}
132             return allocator
133
134     microopClasses["limm"] = LimmOp
...
161 let {{
162     # Build up the all register version of this micro op
163     iops = [InstObjParams("limm", "Limm", 'X86MicroopBase',
164             {"code" : "DestReg = merge(DestReg, imm, dataSize);"}),
165             InstObjParams("limm", "LimmBig", 'X86MicroopBase',
166             {"code" : "DestReg = imm & mask(dataSize * 8);"})]
167     for iop in iops:
168         header_output += MicroLimmOpDeclare.subst(iop)
169         decoder_output += MicroLimmOpConstructor.subst(iop)
170         decoder_output += MicroLimmOpDisassembly.subst(iop)
171         exec_output += MicroLimmOpExecute.subst(iop)
{% endraw %}
```
### Define python microop class
When we look at the first let block,
we can find familiar python class definition for limm microop.
As we've seen in the previous posting,
macroop container initiates python microop classes.

This python microop class, 
especially getAllocator definition of it,
is used in CPP macroop class generation.
As shown in the constructor part of the LimmOp class, 
it sets classname field as *Limm* 
which is the CPP class name of Limm microop.
Also, based on this name,
getAllocator function generates doc string 
that contains instantiation code for CPP microop class Limm.

### Generate CPP microop class
To initiate CPP instance of Limm microop class,
actual implementation of class declaration, definition, 
constructor, and memeber functions
of the microop class.

The second let block in the above code 
retrieves all implementation 
required for generating CPP microop class. 
It mainly makes use of InstObjParams and several templates.

Although each microop class can be implemented one by one 
by the GEM5 programmar, 
because several microops have similar semantics
it makes use of general templates and 
string substitution that customize templates 
for each microops. 

For this microop specific accommodation to templates,
it makes use of *InstObjParams*.
One microop specific information 
can be represented by one InstObjParams instance.
For example, 
code part of it can vary depending on the microop.

### InstObjParams required for generating different microop implementation
*gem5/src/arch/isa_parser.py*
```python
1413 class InstObjParams(object):
1414     def __init__(self, parser, mnem, class_name, base_class = '',
1415                  snippets = {}, opt_args = []):
1416         self.mnemonic = mnem
1417         self.class_name = class_name
1418         self.base_class = base_class
1419         if not isinstance(snippets, dict):
1420             snippets = {'code' : snippets}
1421         compositeCode = ' '.join(map(str, snippets.values()))
1422         self.snippets = snippets
1423
1424         self.operands = OperandList(parser, compositeCode)
1425
1426         # The header of the constructor declares the variables to be used
1427         # in the body of the constructor.
1428         header = ''
1429         header += '\n\t_numSrcRegs = 0;'
1430         header += '\n\t_numDestRegs = 0;'
1431         header += '\n\t_numFPDestRegs = 0;'
1432         header += '\n\t_numVecDestRegs = 0;'
1433         header += '\n\t_numVecElemDestRegs = 0;'
1434         header += '\n\t_numVecPredDestRegs = 0;'
1435         header += '\n\t_numIntDestRegs = 0;'
1436         header += '\n\t_numCCDestRegs = 0;'
1437
1438         self.constructor = header + \
1439                            self.operands.concatAttrStrings('constructor')
1440
1441         self.flags = self.operands.concatAttrLists('flags')
1442
1443         self.op_class = None
1444
1445         # Optional arguments are assumed to be either StaticInst flags
1446         # or an OpClass value.  To avoid having to import a complete
1447         # list of these values to match against, we do it ad-hoc
1448         # with regexps.
1449         for oa in opt_args:
1450             if instFlagRE.match(oa):
1451                 self.flags.append(oa)
1452             elif opClassRE.match(oa):
1453                 self.op_class = oa
1454             else:
1455                 error('InstObjParams: optional arg "%s" not recognized '
1456                       'as StaticInst::Flag or OpClass.' % oa)
1457
1458         # Make a basic guess on the operand class if not set.
1459         # These are good enough for most cases.
1460         if not self.op_class:
1461             if 'IsStore' in self.flags:
1462                 # The order matters here: 'IsFloating' and 'IsInteger' are
1463                 # usually set in FP instructions because of the base
1464                 # register
1465                 if 'IsFloating' in self.flags:
1466                     self.op_class = 'FloatMemWriteOp'
1467                 else:
1468                     self.op_class = 'MemWriteOp'
1469             elif 'IsLoad' in self.flags or 'IsPrefetch' in self.flags:
1470                 # The order matters here: 'IsFloating' and 'IsInteger' are
1471                 # usually set in FP instructions because of the base
1472                 # register
1473                 if 'IsFloating' in self.flags:
1474                     self.op_class = 'FloatMemReadOp'
1475                 else:
1476                     self.op_class = 'MemReadOp'
1477             elif 'IsFloating' in self.flags:
1478                 self.op_class = 'FloatAddOp'
1479             elif 'IsVector' in self.flags:
1480                 self.op_class = 'SimdAddOp'
1481             else:
1482                 self.op_class = 'IntAluOp'
1483
1484         # add flag initialization to contructor here to include
1485         # any flags added via opt_args
1486         self.constructor += makeFlagConstructor(self.flags)
1487
1488         # if 'IsFloating' is set, add call to the FP enable check
1489         # function (which should be provided by isa_desc via a declare)
1490         # if 'IsVector' is set, add call to the Vector enable check
1491         # function (which should be provided by isa_desc via a declare)
1492         if 'IsFloating' in self.flags:
1493             self.fp_enable_check = 'fault = checkFpEnableFault(xc);'
1494         elif 'IsVector' in self.flags:
1495             self.fp_enable_check = 'fault = checkVecEnableFault(xc);'
1496         else:
1497             self.fp_enable_check = ''
```

## templates and string substitution
When we look at the last let block once again,
we can find that four templates are used with substitution
for generating header, decoder, and exec output.
The generated implementation are respectively written in 
decoder-ns.hh.inc, decoder-ns.cc.inc, exec-ns.cc.inc files.

Templates generating constructor and execute function 
are mostly important in Limm microop class generation.
Also it provides enough information 
to understand rest of the templates,
let's take a look at MicroLimmOpExecute and MicroLimmOpConstructor.

### MicroLimmOpConstructor: generate constructor for Limm microop class
```python
{% raw %}
 92 def template MicroLimmOpConstructor {{
 93     %(class_name)s::%(class_name)s(
 94             ExtMachInst machInst, const char * instMnem, uint64_t setFlags,
 95             InstRegIndex _dest, uint64_t _imm, uint8_t _dataSize) :
 96         %(base_class)s(machInst, "%(mnemonic)s", instMnem,
 97                 setFlags, %(op_class)s),
 98                 dest(_dest.index()), imm(_imm), dataSize(_dataSize)
 99     {
100         foldOBit = (dataSize == 1 && !machInst.rex.present) ? 1 << 6 : 0;
101         %(constructor)s;
102     }
103 }};
{% endraw %}
```
Constructor template generates a class constructor for Limm microop.
Note that this constructor is used 
to instantiate Limm microop object
by the getAllocator function.

### Mystery-between python operand and cpp operand
Because this constructor invocation code is generated 
through the LimmOp python class,
all the parameters required for Limm microop construction
are fed from the LimmOp. 

Remeber that when LimmOp python class is instantiated,
it needs several operands 
such as dest, imm, dataSize.
These operands are retrieved 
from the microcode implementation of macroop
and translated into another string 
as a result of eval (for detail please refet xxx).

This translation was required because 
user-friendly microop operands 
should be translated into actual CPP code
that can be interpreted by the core. 
For example, register name such as rax, t1 can be used 
to program with microops, but
it cannot be directly used by the core to access physical registers.
Therefore, translation is required,
and each ISA register is translated into register index 
such as InstRegIndex(NUM_INTREGS+1).

Although I got sidetracked little bit,
note that constructor of Limm microop class 
requires InstRegIndex type operand 
used for setting destination register.
Yes, that is the type of translated operand.  

###String replacement in MicroLimmOpConstructor
Although most of the MicroLimmOpConstructor template 
has been implemented,
there are unfinished part that should be replaced with.
And the replacement content is fed by 
an InstObjParams instance.  

Each template is translated as Template python class 
with the help of isa_parser. 
Therefore, as shown in the second let block,
each template can invokes subst method 
to substitute InstObjParams for unfinished part of template.

subst definition makes use of python dictionary *__dict__* 
that contains object's attributes.
When subst takes InstObjParams,
it expands dictionary of InstObjParams by adding 
some mappings required for template substitution 
such as op_rd.
However, bascially, most of the required dictionary for substitution
is retrieved from the InstObjParams. 

The *constructor* attribute is also excerpted from InstObjParams.
```python
{% raw %}
1426         # The header of the constructor declares the variables to be used
1427         # in the body of the constructor.
1428         header = ''
1429         header += '\n\t_numSrcRegs = 0;'
1430         header += '\n\t_numDestRegs = 0;'
1431         header += '\n\t_numFPDestRegs = 0;'
1432         header += '\n\t_numVecDestRegs = 0;'
1433         header += '\n\t_numVecElemDestRegs = 0;'
1434         header += '\n\t_numVecPredDestRegs = 0;'
1435         header += '\n\t_numIntDestRegs = 0;'
1436         header += '\n\t_numCCDestRegs = 0;'
1437
1438         self.constructor = header + \
1439                            self.operands.concatAttrStrings('constructor')
...
1484         # add flag initialization to contructor here to include
1485         # any flags added via opt_args
1486         self.constructor += makeFlagConstructor(self.flags)
{% endraw %}
```
Inside the InstObjParams constructor,
there are several assignments 
to the self.constructor attribute
which will be used for 
replacing %(constructor)s in the template.

Before we go into detail,
let's check out the generated constructor code 
for Limm microop class.

*gem5/build/X86/arch/x86/generated/decoder-ns.cc.inc*
{% raw %}
```python
 10385     Limm::Limm(
 10386             ExtMachInst machInst, const char * instMnem, uint64_t setFlags,
 10387             InstRegIndex _dest, uint64_t _imm, uint8_t _dataSize) :
 10388         X86MicroopBase(machInst, "limm", instMnem,
 10389                 setFlags, IntAluOp),
 10390                 dest(_dest.index()), imm(_imm), dataSize(_dataSize)
 10391     {
 10392         foldOBit = (dataSize == 1 && !machInst.rex.present) ? 1 << 6 : 0;
 10393
 10394         _numSrcRegs = 0;
 10395         _numDestRegs = 0;
 10396         _numFPDestRegs = 0;
 10397         _numVecDestRegs = 0;
 10398         _numVecElemDestRegs = 0;
 10399         _numVecPredDestRegs = 0;
 10400         _numIntDestRegs = 0;
 10401         _numCCDestRegs = 0;
 10402         _srcRegIdx[_numSrcRegs++] = RegId(IntRegClass, INTREG_FOLDED(dest, foldOBit));
 10403         _destRegIdx[_numDestRegs++] = RegId(IntRegClass, INTREG_FOLDED(dest, foldOBit));
 10404         _numIntDestRegs++;
 10405         flags[IsInteger] = true;;
 10406     }
```
{% endraw %}

When we compare 
update statements to constructor attribute 
and 
generated code,
we can easily understand which part of the initialization code 
has been generated by which update statement.

Line 10394-10401 matches with first update to constructor attribute
which generates variable initialization. 
Importantly, line 10402-10404
clarifies which register is used as destination and source 
of the microop operation. 

These two initialization statements are generated from 
the first update to constructor attribute (line 1438-1439).
Because header is a static string shown on the code,
let's talk about the second part 
derived from operands.

When operands of InstObjParams invokes concatAttrStrings, 
it iterates parsed operands and 
extracts values from attributes constructor
and concatenates them all to generate one string.
Because constructor attributes of OperandList 
is used to get microop specific constructor codes
we need to understand how the attribute is 
generated by the OperandList.

### OperandList parse operands from code snippets
OperandList parses code snippets of microop
and generate *Operand* objects 
representing arguments of microop.
Because each Operand 
provides useful information to 
constructor creation and defining execute function of microop,
it should be parsed before substituting templates

OperandList parses code snippets with 
regular expression and 
translate each tokens to 
a code block that 
updates or accesses register
depending on destination and source.

Let's take a look at code snippet
used for generating class for microop Limm.

```python
163     iops = [InstObjParams("limm", "Limm", 'X86MicroopBase',
164             {"code" : "DestReg = merge(DestReg, imm, dataSize);"}),
165             InstObjParams("limm", "LimmBig", 'X86MicroopBase',
166             {"code" : "DestReg = imm & mask(dataSize * 8);"})]
```

We can infer that DestReg, imm, dataSize are
input operands of Limm microop 
from the fact that LimmOp python class requires three parameters
(dest, imm, and dataSize).
Also, because DestReg is updated 
with the merged result,
we can infer that DestReg is also used a destination register.


### Deep dive into OperandList
{% raw %}
```python
1127 class OperandList(object):
1128     '''Find all the operands in the given code block.  Returns an operand
1129     descriptor list (instance of class OperandList).'''
1130     def __init__(self, parser, code):
1131         self.items = []
1132         self.bases = {}
1133         # delete strings and comments so we don't match on operands inside
1134         for regEx in (stringRE, commentRE):
1135             code = regEx.sub('', code)
1136         # search for operands
1137         next_pos = 0
1138         while 1:
1139             match = parser.operandsRE.search(code, next_pos)
1140             if not match:
1141                 # no more matches: we're done
1142                 break
1143             op = match.groups()
1144             # regexp groups are operand full name, base, and extension
1145             (op_full, op_base, op_ext) = op
1146             # If is a elem operand, define or update the corresponding
1147             # vector operand
1148             isElem = False
1149             if op_base in parser.elemToVector:
1150                 isElem = True
1151                 elem_op = (op_base, op_ext)
1152                 op_base = parser.elemToVector[op_base]
1153                 op_ext = '' # use the default one
1154             # if the token following the operand is an assignment, this is
1155             # a destination (LHS), else it's a source (RHS)
1156             is_dest = (assignRE.match(code, match.end()) != None)
1157             is_src = not is_dest
1158
1159             # see if we've already seen this one
1160             op_desc = self.find_base(op_base)
1161             if op_desc:
1162                 if op_ext and op_ext != '' and op_desc.ext != op_ext:
1163                     error ('Inconsistent extensions for operand %s: %s - %s' \
1164                             % (op_base, op_desc.ext, op_ext))
1165                 op_desc.is_src = op_desc.is_src or is_src
1166                 op_desc.is_dest = op_desc.is_dest or is_dest
1167                 if isElem:
1168                     (elem_base, elem_ext) = elem_op
1169                     found = False
1170                     for ae in op_desc.active_elems:
1171                         (ae_base, ae_ext) = ae
1172                         if ae_base == elem_base:
1173                             if ae_ext != elem_ext:
1174                                 error('Inconsistent extensions for elem'
1175                                       ' operand %s' % elem_base)
1176                             else:
1177                                 found = True
1178                     if not found:
1179                         op_desc.active_elems.append(elem_op)
1180             else:
1181                 # new operand: create new descriptor
1182                 op_desc = parser.operandNameMap[op_base](parser,
1183                     op_full, op_ext, is_src, is_dest)
1184                 # if operand is a vector elem, add the corresponding vector
1185                 # operand if not already done
1186                 if isElem:
1187                     op_desc.elemExt = elem_op[1]
1188                     op_desc.active_elems = [elem_op]
1189                 self.append(op_desc)
1190             # start next search after end of current match
1191             next_pos = match.end()
1192         self.sort()
1193         # enumerate source & dest register operands... used in building
1194         # constructor later
1195         self.numSrcRegs = 0
1196         self.numDestRegs = 0
1197         self.numFPDestRegs = 0
1198         self.numIntDestRegs = 0
1199         self.numVecDestRegs = 0
1200         self.numVecPredDestRegs = 0
1201         self.numCCDestRegs = 0
1202         self.numMiscDestRegs = 0
1203         self.memOperand = None
1204
1205         # Flags to keep track if one or more operands are to be read/written
1206         # conditionally.
1207         self.predRead = False
1208         self.predWrite = False
1209
1210         for op_desc in self.items:
1211             if op_desc.isReg():
1212                 if op_desc.is_src:
1213                     op_desc.src_reg_idx = self.numSrcRegs
1214                     self.numSrcRegs += 1
1215                 if op_desc.is_dest:
1216                     op_desc.dest_reg_idx = self.numDestRegs
1217                     self.numDestRegs += 1
1218                     if op_desc.isFloatReg():
1219                         self.numFPDestRegs += 1
1220                     elif op_desc.isIntReg():
1221                         self.numIntDestRegs += 1
1222                     elif op_desc.isVecReg():
1223                         self.numVecDestRegs += 1
1224                     elif op_desc.isVecPredReg():
1225                         self.numVecPredDestRegs += 1
1226                     elif op_desc.isCCReg():
1227                         self.numCCDestRegs += 1
1228                     elif op_desc.isControlReg():
1229                         self.numMiscDestRegs += 1
1230             elif op_desc.isMem():
1231                 if self.memOperand:
1232                     error("Code block has more than one memory operand.")
1233                 self.memOperand = op_desc
1234
1235             # Check if this operand has read/write predication. If true, then
1236             # the microop will dynamically index source/dest registers.
1237             self.predRead = self.predRead or op_desc.hasReadPred()
1238             self.predWrite = self.predWrite or op_desc.hasWritePred()
1239
1240         if parser.maxInstSrcRegs < self.numSrcRegs:
1241             parser.maxInstSrcRegs = self.numSrcRegs
1242         if parser.maxInstDestRegs < self.numDestRegs:
1243             parser.maxInstDestRegs = self.numDestRegs
1244         if parser.maxMiscDestRegs < self.numMiscDestRegs:
1245             parser.maxMiscDestRegs = self.numMiscDestRegs
1246
1247         # now make a final pass to finalize op_desc fields that may depend
1248         # on the register enumeration
1249         for op_desc in self.items:
1250             op_desc.finalize(self.predRead, self.predWrite)
```
{% endraw %}

Although it is very complicated and long function,
it stores parsed operands to the self.items
through the self.append(op_desc) in line 1189.
After parinsg the operands,
it iterates every parsed operands stored in self.items
and invokes finalize function of each operand.

The type of items can be any classes inheriting *Operand class*.
When a new operand is found (line 1180-1191),
it searches operandNameMap of parser 
to generates a new operand descriptor.

###Operand parsing and operandNameMap
It seems that operandNameMap contains class reference 
to initiate new operand descriptor 
for a parsed operands.
Then where the operandNameMap brings 
required information for generating a operand to class map? 

*gem5/src/arch/x86/isa/operands.isa*
```python
 91 def operands {{
 92         'SrcReg1':       foldInt('src1', 'foldOBit', 1),
 93         'SSrcReg1':      intReg('src1', 1),
 94         'SrcReg2':       foldInt('src2', 'foldOBit', 2),
 95         'SSrcReg2':      intReg('src2', 1),
 96         'Index':         foldInt('index', 'foldABit', 3),
 97         'Base':          foldInt('base', 'foldABit', 4),
 98         'DestReg':       foldInt('dest', 'foldOBit', 5),
 99         'SDestReg':      intReg('dest', 5),
100         'Data':          foldInt('data', 'foldOBit', 6),
101         'DataLow':       foldInt('dataLow', 'foldOBit', 6),
102         'DataHi':        foldInt('dataHi', 'foldOBit', 6),
103         'ProdLow':       impIntReg(0, 7),
104         'ProdHi':        impIntReg(1, 8),
105         'Quotient':      impIntReg(2, 9),
106         'Remainder':     impIntReg(3, 10),
107         'Divisor':       impIntReg(4, 11),
108         'DoubleBits':    impIntReg(5, 11),
109         'Rax':           intReg('(INTREG_RAX)', 12),
110         'Rbx':           intReg('(INTREG_RBX)', 13),
111         'Rcx':           intReg('(INTREG_RCX)', 14),
112         'Rdx':           intReg('(INTREG_RDX)', 15),
113         'Rsp':           intReg('(INTREG_RSP)', 16),
114         'Rbp':           intReg('(INTREG_RBP)', 17),
115         'Rsi':           intReg('(INTREG_RSI)', 18),
116         'Rdi':           intReg('(INTREG_RDI)', 19),
```
As shown in the above operands definition,
each architecture defines operands list 
that can be used by microops.
You can see DestReg is also registered as X86 operand (Line 98).

*gem5/src/arch/isa_parser.py*
```python
2066     # Define the mapping from operand names to operand classes and
2067     # other traits.  Stored in operandNameMap.
2068     def p_def_operands(self, t):
2069         'def_operands : DEF OPERANDS CODELIT SEMI'
2070         if not hasattr(self, 'operandTypeMap'):
2071             error(t.lineno(1),
2072                   'error: operand types must be defined before operands')
2073         try:
2074             user_dict = eval('{' + t[3] + '}', self.exportContext)
2075         except Exception, exc:
2076             if debug:
2077                 raise
2078             error(t.lineno(1), 'In def operands: %s' % exc)
2079         self.buildOperandNameMap(user_dict, t.lexer.lineno)
```
The defined operands are parsed by the isa_parser
as other isa definition does. 
As shown on the above grammar rule,
when the def operands block is found,
it invokes buildOperandNameMap function 
and generates operandNameMap.

We are not going to cover details, but
it provides mapping between
operands name to operand class used 
for accessing that operands
in the automatically generated CPP microop class implmentation.


###finalize function generates actual code statements for operand
After operands are successfully parsed from the code snippets,
it generates corresponding operands classes 
stored in the self.items. 
Because we need a code block that makes the generated CPP microop class
access the actual operands,
it needs code generation through *finalize* method.

Although depending on the operand type,
it invokes differnt version of finalize,
we will take a look at finalize of 
base class for operand descriptors, class Operand.
This is because most of the children classes of Operand 
doesn't override the finalize method.

```python
 450     def finalize(self, predRead, predWrite):
 451         self.flags = self.getFlags()
 452         self.constructor = self.makeConstructor(predRead, predWrite)
 453         self.op_decl = self.makeDecl()
 454
 455         if self.is_src:
 456             self.op_rd = self.makeRead(predRead)
 457             self.op_src_decl = self.makeDecl()
 458         else:
 459             self.op_rd = ''
 460             self.op_src_decl = ''
 461
 462         if self.is_dest:
 463             self.op_wb = self.makeWrite(predWrite)
 464             self.op_dest_decl = self.makeDecl()
 465         else:
 466             self.op_wb = ''
 467             self.op_dest_decl = ''
```

depending on the operand type 
such as read/write, 
it generates corresponding code 
that can actually read/write from/to the operands
(e.g., from registers).

The finalize method generates mainly two code bloks:
initialization code for operands generated by *makeConstructor*
and operands accessing code retrieved by *makeRead* and *makeWrite*.

Because in our case, 
first operand, *DestReg* is *IntRegOperand* object,
it will eventually ends up invoking several 
methods defined in there. 

###makeConstructor: generate constructor code for operands 
{% raw %}
```python
 524 src_reg_constructor = '\n\t_srcRegIdx[_numSrcRegs++] = RegId(%s, %s);'
 525 dst_reg_constructor = '\n\t_destRegIdx[_numDestRegs++] = RegId(%s, %s);'
 528 class IntRegOperand(Operand):
 529     reg_class = 'IntRegClass'
 530
 531     def isReg(self):
 532         return 1
 533
 534     def isIntReg(self):
 535         return 1
 536
 537     def makeConstructor(self, predRead, predWrite):
 538         c_src = ''
 539         c_dest = ''
 540
 541         if self.is_src:
 542             c_src = src_reg_constructor % (self.reg_class, self.reg_spec)
 543             if self.hasReadPred():
 544                 c_src = '\n\tif (%s) {%s\n\t}' % \
 545                         (self.read_predicate, c_src)
 546
 547         if self.is_dest:
 548             c_dest = dst_reg_constructor % (self.reg_class, self.reg_spec)
 549             c_dest += '\n\t_numIntDestRegs++;'
 550             if self.hasWritePred():
 551                 c_dest = '\n\tif (%s) {%s\n\t}' % \
 552                          (self.write_predicate, c_dest)
 553
 554         return c_src + c_dest
 555
```
{% endraw %}

To get to the point, 
makeConstructor generates below code blocks
used in the constructor of Limm microop class.

```cpp
 10402         _srcRegIdx[_numSrcRegs++] = RegId(IntRegClass, INTREG_FOLDED(dest, foldOBit));
 10403         _destRegIdx[_numDestRegs++] = RegId(IntRegClass, INTREG_FOLDED(dest, foldOBit));
```

Because we are currently dealing with DestReg on the LHS 
used as a destination operand,
line 547-553 will be executed.
It generate a code statement that assign RegId object 
to *destRegIdx* array.
Because *_destRegIdx* array is a member field of *StaticInst* class,
the generated code stores 
RegId information about DestReg operand 
to the Limm microop instance which inherits from StaticInst.

Regarding RegId instance generation,
it makes use of self.reg_spec and self.reg_class .
for the details please look at the 
operandMap and operand definition
implemented in operands.isa and isa_parser.py files.

###makeRead, makeWrite: generate operands accessing code
After construction code for operands are executed,
it will pish operands related information 
in associated microop class

Then how the actual microop implementation can
access those operands?
let's take a look at makeRead and makeWrite implementation of 
IntRegOperand class. 

{% raw %}
```python
 556     def makeRead(self, predRead):
 557         if (self.ctype == 'float' or self.ctype == 'double'):
 558             error('Attempt to read integer register as FP')
 559         if self.read_code != None:
 560             return self.buildReadCode('readIntRegOperand')
 561
 562         int_reg_val = ''
 563         if predRead:
 564             int_reg_val = 'xc->readIntRegOperand(this, _sourceIndex++)'
 565             if self.hasReadPred():
 566                 int_reg_val = '(%s) ? %s : 0' % \
 567                               (self.read_predicate, int_reg_val)
 568         else:
 569             int_reg_val = 'xc->readIntRegOperand(this, %d)' % self.src_reg_idx
 570
 571         return '%s = %s;\n' % (self.base_name, int_reg_val)
 572
 573     def makeWrite(self, predWrite):
 574         if (self.ctype == 'float' or self.ctype == 'double'):
 575             error('Attempt to write integer register as FP')
 576         if self.write_code != None:
 577             return self.buildWriteCode('setIntRegOperand')
 578
 579         if predWrite:
 580             wp = 'true'
 581             if self.hasWritePred():
 582                 wp = self.write_predicate
 583
 584             wcond = 'if (%s)' % (wp)
 585             windex = '_destIndex++'
 586         else:
 587             wcond = ''
 588             windex = '%d' % self.dest_reg_idx
 589
 590         wb = '''
 591         %s
 592         {
 593             %s final_val = %s;
 594             xc->setIntRegOperand(this, %s, final_val);\n
 595             if (traceData) { traceData->setData(final_val); }
 596         }''' % (wcond, self.ctype, self.base_name, windex)
 597
 598         return wb
```
{% endraw %}
In a situation where
a microop wants to write data to the destination operand,
the required code blocks are generated by the makeWrite function.

Because DestReg operand doesn't provide specific write_code,
it executes line 590-598.
Also because DestReg is not a predWrite,
it sets windex from dest_reg_idx field of Operand.
Note that this is not a actual register index 
that can access the core register such as t1,
but it is an index 
that can reference RegID stored in the 
_destRegIdx array.

Actual store operation is done by 
*setIntRegOperand* method of ExecContext.
Note that this method requires staticInst (this)
index (windx), and final_val to be stored.
setIntRegOperand method retrieves RegID
by indexing _destRegIdx of passed staticInst
using the index operand.

Because
above code is executed as part of
execute function defined in 
microop Limm class,
*this* means Limm microop class itself
which contains operands in the _destRegIdx array.

{% raw %}
```python
 44 def template MicroLimmOpExecute {{
 45         Fault %(class_name)s::execute(ExecContext *xc,
 46                 Trace::InstRecord *traceData) const
 47         {
 48             %(op_decl)s;
 49             %(op_rd)s;
 50             %(code)s;
 51             %(op_wb)s;
 52             return NoFault;
 53         }
 54 }};
```
{% endraw %}

{% raw %}
```cpp
19047         Fault Limm::execute(ExecContext *xc,
19048                 Trace::InstRecord *traceData) const
19049         {
19050             uint64_t DestReg = 0;
19051 ;
19052             DestReg = xc->readIntRegOperand(this, 0);
19053 ;
19054             DestReg = merge(DestReg, imm, dataSize);;
19055
19056
19057         {
19058             uint64_t final_val = DestReg;
19059             xc->setIntRegOperand(this, 0, final_val);
19060
19061             if (traceData) { traceData->setData(final_val); }
19062         };
19063             return NoFault;
19064         }
```
{% endraw %}

