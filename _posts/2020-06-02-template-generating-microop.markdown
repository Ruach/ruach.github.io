




---
layout: post
titile: "GEM5 Template to replace code-literal"
categories: [GEM5, Microops]
---
# Automatic CPP Class Generation for Macroop and Microop
 This ISA includes 
macroop and microops of X86 architecture. Therefore, to understand how GEM5 
defines ISA, and how they are automatically translated into CPP classes, you 
should understand how PLY works. It is highly recommended to read 
[this link][1].


When you open the isa files in src/arch/x86/isa/microops/ directory, you will   
notice that it has two different types of statements defining the microop: **let 
block and def template**. Let's take a look at the grammar rule for let block.  


Although actual simulation is achieved through the CPP implementations, GEM5    
utilizes python to generate the CPP implementation automatically based on what   
the python classes define about each ISA. Therefore, the ISA file is usually    
defines the python class required for representing ISA, especially the macroop  
and microop in our X86 case.                                                    
                                                                                
```python                                                                       
let {                                                                           
    class LdStOp(X86Microop):                                                   
        def __init__(self, data, segment, addr, disp,                           
                dataSize, addressSize, baseFlags, atCPL0, prefetch, nonSpec,    
                implicitStack, uncacheable):                                    
            self.data = data                                                    
            [self.scale, self.index, self.base] = addr                          
            self.disp = disp                                                    
            self.segment = segment                                              
            self.dataSize = dataSize                                            
            self.addressSize = addressSize                                      
            self.memFlags = baseFlags                                           
            if atCPL0:                                                          
                self.memFlags += " | (CPL0FlagBit << FlagShift)"                
            self.instFlags = ""                                                 
            if prefetch:                                                        
                self.memFlags += " | Request::PREFETCH"                         
                self.instFlags += " | (1ULL << StaticInst::IsDataPrefetch)"     
            if nonSpec:                                                         
                self.instFlags += " | (1ULL << StaticInst::IsNonSpeculative)"   
            if uncacheable:                                                     
                self.instFlags += " | (Request::UNCACHEABLE)"                   
            # For implicit stack operations, we should use *not* use the        
            # alternative addressing mode for loads/stores if the prefix is set 
            if not implicitStack:                                               
                self.memFlags += " | (machInst.legacy.addr ? " + \              
                                 "(AddrSizeFlagBit << FlagShift) : 0)"          
                                                                                
            ......                                                              
}                                                                               
```                                                                             
                                                                                


### def template ID {...};
#### def template example
```python
def template MicroLeaExecute {
    Fault %(class_name)s::execute(ExecContext *xc,
          Trace::InstRecord *traceData) const
    {
        Fault fault = NoFault;
        Addr EA;

        %(op_decl)s;
        %(op_rd)s;
        %(ea_code)s;
        DPRINTF(X86, "%s : %s: The address is %#x\n", instMnem, mnemonic, EA);

        %(code)s;
        if(fault == NoFault)
        {
            %(op_wb)s;
        }

        return fault;
    }
};

```

#### def template grammar rule
```python
*gem5/src/arch/isa_parser.py*

    def p_def_template(self, t):
        'def_template : DEF TEMPLATE ID CODELIT SEMI'
        if t[3] in self.templateMap:
            print("warning: template %s already defined" % t[3])
        self.templateMap[t[3]] = Template(self, t[4])

```

As shown in the grammar rule, 
Template object is instantiated with the code literal 
of the def template block, t[4].
The newly instantiated Template objects will be maintained 
by the templateMap of the parser.
Note that its template name (t[3], ID) 
will be used to index the generated Template object 
inside the map. 
The GEM5 parser defines Template python class for this purpose. 

```python
 106 ####################
 107 # Template objects.
 108 #
 109 # Template objects are format strings that allow substitution from
 110 # the attribute spaces of other objects (e.g. InstObjParams instances).
 111 
 112 labelRE = re.compile(r'(?<!%)%\(([^\)]+)\)[sd]')
 113 
 114 class Template(object):
 115     def __init__(self, parser, t):
 116         self.parser = parser
 117         self.template = t
 118 
 119     def subst(self, d):
 120         myDict = None
 121 
 122         # Protect non-Python-dict substitutions (e.g. if there's a printf
 123         # in the templated C++ code)
 124         template = self.parser.protectNonSubstPercents(self.template)
 125 
 126         # Build a dict ('myDict') to use for the template substitution.
 127         # Start with the template namespace.  Make a copy since we're
 128         # going to modify it.
 129         myDict = self.parser.templateMap.copy()
 130 
 131         if isinstance(d, InstObjParams):
 132             # If we're dealing with an InstObjParams object, we need
 133             # to be a little more sophisticated.  The instruction-wide
 134             # parameters are already formed, but the parameters which
 135             # are only function wide still need to be generated.
 136             compositeCode = ''
 137 
 138             myDict.update(d.__dict__)
 139             # The "operands" and "snippets" attributes of the InstObjParams
 140             # objects are for internal use and not substitution.
 141             del myDict['operands']
 142             del myDict['snippets']
 143 
 144             snippetLabels = [l for l in labelRE.findall(template)
 145                              if l in d.snippets]
 146 
 147             snippets = dict([(s, self.parser.mungeSnippet(d.snippets[s]))
 148                              for s in snippetLabels])
 149 
 150             myDict.update(snippets)
 151 
 152             compositeCode = ' '.join(map(str, snippets.values()))
 153 
 154             # Add in template itself in case it references any
 155             # operands explicitly (like Mem)
 156             compositeCode += ' ' + template
 157 
 158             operands = SubOperandList(self.parser, compositeCode, d.operands)
 159 
 160             myDict['op_decl'] = operands.concatAttrStrings('op_decl')
 161             if operands.readPC or operands.setPC:
 162                 myDict['op_decl'] += 'TheISA::PCState __parserAutoPCState;\n'
 163 
 164             # In case there are predicated register reads and write, declare
 165             # the variables for register indicies. It is being assumed that
 166             # all the operands in the OperandList are also in the
 167             # SubOperandList and in the same order. Otherwise, it is
 168             # expected that predication would not be used for the operands.
 169             if operands.predRead:
 170                 myDict['op_decl'] += 'uint8_t _sourceIndex = 0;\n'
 171             if operands.predWrite:
 172                 myDict['op_decl'] += 'uint8_t M5_VAR_USED _destIndex = 0;\n'
 173 
 174             is_src = lambda op: op.is_src
 175             is_dest = lambda op: op.is_dest
 176 
 177             myDict['op_src_decl'] = \
 178                       operands.concatSomeAttrStrings(is_src, 'op_src_decl')
 179             myDict['op_dest_decl'] = \
 180                       operands.concatSomeAttrStrings(is_dest, 'op_dest_decl')
 181             if operands.readPC:
 182                 myDict['op_src_decl'] += \
 183                     'TheISA::PCState __parserAutoPCState;\n'
 184             if operands.setPC:
 185                 myDict['op_dest_decl'] += \
 186                     'TheISA::PCState __parserAutoPCState;\n'
 187 
 188             myDict['op_rd'] = operands.concatAttrStrings('op_rd')
 189             if operands.readPC:
 190                 myDict['op_rd'] = '__parserAutoPCState = xc->pcState();\n' + \
 191                                   myDict['op_rd']
 192 
 193             # Compose the op_wb string. If we're going to write back the
 194             # PC state because we changed some of its elements, we'll need to
 195             # do that as early as possible. That allows later uncoordinated
 196             # modifications to the PC to layer appropriately.
 197             reordered = list(operands.items)
 198             reordered.reverse()
 199             op_wb_str = ''
 200             pcWbStr = 'xc->pcState(__parserAutoPCState);\n'
 201             for op_desc in reordered:
 202                 if op_desc.isPCPart() and op_desc.is_dest:
 203                     op_wb_str = op_desc.op_wb + pcWbStr + op_wb_str
 204                     pcWbStr = ''
 205                 else:
 206                     op_wb_str = op_desc.op_wb + op_wb_str
 207             myDict['op_wb'] = op_wb_str
 208 
 209         elif isinstance(d, dict):
 210             # if the argument is a dictionary, we just use it.
 211             myDict.update(d)
 212         elif hasattr(d, '__dict__'):
 213             # if the argument is an object, we use its attribute map.
 214             myDict.update(d.__dict__)
 215         else:
 216             raise TypeError, "Template.subst() arg must be or have dictionary"
 217         return template % myDict
 218 
 219     # Convert to string.
 220     def __str__(self):
 221         return self.template
```

When the Template object is instantiated, 
its code-literal will be stored
in the self.template field of the Template object. 
This template field will be used later in the subst method 
to substitute code-literal following the substitution string.

One important definition provided by the Template class is **subst**. 
You can see that it returns template (code literal string)
substituted with myDict. 
Note that the passed code literal contains unfinished parts 
that should be replaced before generating complete CPP statements. 
Therefore, the subst function creates the myDict 
based on the object passed to the subst, d.
Usually, this passed object is InstObjParams providing 
microop or macroop specific information to complete 
general implementation provided by the template. 
Note that subst function manages myDict dictionary differently 
based on the type of the object passed to the subst function.
When the InstObjParams type of object is passed,
depending on the information provided by the items 
such as whether it is used for declaration, op_decl,
or for data write-back, op_wb,
it prepares myDict dictionary properly for later substitution.  

## Automatically define CPP classes and associated methods for microop using template
In the previous posting, we took a look at how the python class dedicated for 
one microop can be used to represent macroop and microop. 
Also, we saw that python class for macroop is used to populate
CPP class counterpart that can be compiled with other CPP source code 
(GEM5 is CPP based project not python). 
In the middle of that journey, we saw that the getAllocator function
of the microop python class generates CPP code snippets instantiating 
*CPP microop class* which is the counter part of the microop python class. 
We will see how those CPP classes for microops are generated by utilizing templates. 

### defineMicroLoadOp: define micro-load operations using templates
To understand how the CPP class for one microop can be implemented,
we will take a look at the load related micro instructions in x86 architecture. 
The most important function of this microop class generation is 
the **subst** method provided by the Template object.
GEM5 utilize the substitution a lot to populate 
various instructions having similar semantics.

*gem5/src/arch/x86/isa/microops/ldstop.isa*
```python
{% raw %}
434 let {{
435 
436     # Make these empty strings so that concatenating onto
437     # them will always work.
438     header_output = ""
439     decoder_output = ""
440     exec_output = ""
441 
442     segmentEAExpr = \
443         'bits(scale * Index + Base + disp, addressSize * 8 - 1, 0);'
444 
445     calculateEA = 'EA = SegBase + ' + segmentEAExpr
446 
447     debuggingEA = \
448         'DPRINTF(X86, "EA:%#x index:%#x base:%#x disp:%#x Segbase:%#x scale:%#x, addressSize:%#x, dataSize: %#x \\n", EA, Index, Base, disp, SegBase, scale, addressSize, dataSize)'
449 
450 
451     def defineMicroLoadOp(mnemonic, code, bigCode='',
452                           mem_flags="0", big=True, nonSpec=False,
453                           implicitStack=False):
454         global header_output
455         global decoder_output
456         global exec_output
457         global microopClasses
458         Name = mnemonic
459         name = mnemonic.lower()
460 
461         # Build up the all register version of this micro op
462         iops = [InstObjParams(name, Name, 'X86ISA::LdStOp',
463                               { "code": code,
464                                 "ea_code": calculateEA,
465                                 "memDataSize": "dataSize" })]
466         if big:
467             iops += [InstObjParams(name, Name + "Big", 'X86ISA::LdStOp',
468                                    { "code": bigCode,
469                                      "ea_code": calculateEA,
470                                      "memDataSize": "dataSize" })]
471         for iop in iops:
472             header_output += MicroLdStOpDeclare.subst(iop)
473             decoder_output += MicroLdStOpConstructor.subst(iop)
474             exec_output += MicroLoadExecute.subst(iop)
475             exec_output += MicroLoadInitiateAcc.subst(iop)
476             exec_output += MicroLoadCompleteAcc.subst(iop)
477 
478         if implicitStack:
479             # For instructions that implicitly access the stack, the address
480             # size is the same as the stack segment pointer size, not the
481             # address size if specified by the instruction prefix
482             addressSize = "env.stackSize"
483         else:
484             addressSize = "env.addressSize"
485 
486         base = LdStOp
487         if big:
488             base = BigLdStOp
489         class LoadOp(base):
490             def __init__(self, data, segment, addr, disp = 0,
491                     dataSize="env.dataSize",
492                     addressSize=addressSize,
493                     atCPL0=False, prefetch=False, nonSpec=nonSpec,
494                     implicitStack=implicitStack,
495                     uncacheable=False, EnTlb=False):
496                 super(LoadOp, self).__init__(data, segment, addr,
497                         disp, dataSize, addressSize, mem_flags,
498                         atCPL0, prefetch, nonSpec, implicitStack,
499                         uncacheable, EnTlb)
500                 self.className = Name
501                 self.mnemonic = name
502 
503         microopClasses[name] = LoadOp
504 
505     defineMicroLoadOp('Ld', 'Data = merge(Data, Mem, dataSize);',
506                             'Data = Mem & mask(dataSize * 8);')
507     defineMicroLoadOp('Ldis', 'Data = merge(Data, Mem, dataSize);',
508                               'Data = Mem & mask(dataSize * 8);',
509                                implicitStack=True)
510     defineMicroLoadOp('Ldst', 'Data = merge(Data, Mem, dataSize);',
511                               'Data = Mem & mask(dataSize * 8);',
512                       '(StoreCheck << FlagShift)')
513     defineMicroLoadOp('Ldstl', 'Data = merge(Data, Mem, dataSize);',
514                                'Data = Mem & mask(dataSize * 8);',
515                       '(StoreCheck << FlagShift) | Request::LOCKED_RMW',
516                       nonSpec=True)
{% endraw %}
```

As shown on the line 505-516, 
various load microops are populated by invoking 
defineMicroLoadOp python function. 
Because those microops have similar semantics 
which loads data from memory, 
defineMicroLoadOp function generates different 
microops by substituting generic template with microop-specific code-literals.
You can find that multiple subst definitions from
multiple templates are invoked in the defineMicroLoadOp function (line 472-476)
to generate complete implementation of each microop. 

## Operands and its children classes can handle all operands in GEM5
Before we take a look at how the template is used to generate 
actual code for the microops, we should understand what is the 
InstObjParams and why it is necessary for template substitutions.
To understand InstObjParams, we further need a deeper understanding 
about parameter system deployed by the GEM5.
This includes generic classes to represent parameters of microop and macroop, and 
architecture specific operands and its parsing.

### Generic classes representing various types of operands in GEM5
First of all, we need to understand that GEM5 provide common classes
that can define multiple types of operands regardless of architecture.
We will take a look at the class hierarchies representing various operands. 

*gem5/src/arch/isa_parser.py*
```python 
 396 class Operand(object):
 397     '''Base class for operand descriptors.  An instance of this class
 398     (or actually a class derived from this one) represents a specific
 399     operand for a code block (e.g, "Rc.sq" as a dest). Intermediate
 400     derived classes encapsulates the traits of a particular operand
 401     type (e.g., "32-bit integer register").'''
 402 
 403     def buildReadCode(self, func = None):
 404         subst_dict = {"name": self.base_name,
 405                       "func": func,
 406                       "reg_idx": self.reg_spec,
 407                       "ctype": self.ctype}
 408         if hasattr(self, 'src_reg_idx'):
 409             subst_dict['op_idx'] = self.src_reg_idx
 410         code = self.read_code % subst_dict
 411         return '%s = %s;\n' % (self.base_name, code)
 412 
 413     def buildWriteCode(self, func = None):
 414         subst_dict = {"name": self.base_name,
 415                       "func": func,
 416                       "reg_idx": self.reg_spec,
 417                       "ctype": self.ctype,
 418                       "final_val": self.base_name}
 419         if hasattr(self, 'dest_reg_idx'):
 420             subst_dict['op_idx'] = self.dest_reg_idx
 421         code = self.write_code % subst_dict
 422         return '''
 423         {
 424             %s final_val = %s;
 425             %s;
 426             if (traceData) { traceData->setData(final_val); }
 427         }''' % (self.dflt_ctype, self.base_name, code)
 428 
 429     def __init__(self, parser, full_name, ext, is_src, is_dest):
 430         self.full_name = full_name
 431         self.ext = ext
 432         self.is_src = is_src
 433         self.is_dest = is_dest
 434         # The 'effective extension' (eff_ext) is either the actual
 435         # extension, if one was explicitly provided, or the default.
 436         if ext:
 437             self.eff_ext = ext
 438         elif hasattr(self, 'dflt_ext'):
 439             self.eff_ext = self.dflt_ext
 440 
 441         if hasattr(self, 'eff_ext'):
 442             self.ctype = parser.operandTypeMap[self.eff_ext]
 443 
 444     # Finalize additional fields (primarily code fields).  This step
 445     # is done separately since some of these fields may depend on the
 446     # register index enumeration that hasn't been performed yet at the
 447     # time of __init__(). The register index enumeration is affected
 448     # by predicated register reads/writes. Hence, we forward the flags
 449     # that indicate whether or not predication is in use.
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
 468 
 469     def isMem(self):
 470         return 0
 471 
 472     def isReg(self):
 473         return 0
 474 
 475     def isFloatReg(self):
 476         return 0
 477 
 478     def isIntReg(self):
 479         return 0
 480 
 481     def isCCReg(self):
 482         return 0
 483 
 484     def isControlReg(self):
 485         return 0
 486 
 487     def isVecReg(self):
 488         return 0
 489 
 490     def isVecElem(self):
 491         return 0
 492 
 493     def isVecPredReg(self):
 494         return 0
 495 
 496     def isPCState(self):
 497         return 0
 498 
 499     def isPCPart(self):
 500         return self.isPCState() and self.reg_spec
 501 
 502     def hasReadPred(self):
 503         return self.read_predicate != None
 504 
 505     def hasWritePred(self):
 506         return self.write_predicate != None
 507 
 508     def getFlags(self):
 509         # note the empty slice '[:]' gives us a copy of self.flags[0]
 510         # instead of a reference to it
 511         my_flags = self.flags[0][:]
 512         if self.is_src:
 513             my_flags += self.flags[1]
 514         if self.is_dest:
 515             my_flags += self.flags[2]
 516         return my_flags
 517 
 518     def makeDecl(self):
 519         # Note that initializations in the declarations are solely
 520         # to avoid 'uninitialized variable' errors from the compiler.
 521         return self.ctype + ' ' + self.base_name + ' = 0;\n';
 522 
 523 
 524 src_reg_constructor = '\n\t_srcRegIdx[_numSrcRegs++] = RegId(%s, %s);'
 525 dst_reg_constructor = '\n\t_destRegIdx[_numDestRegs++] = RegId(%s, %s);'
```
The **Operand** class is a generic class provides various definitions 
that can be overridden by its children classes.
Only handful of them are overridden to tell 
a type of the current operand class represents.
Let's take a look at IntRegOperand class which inherits the 
base Operand class.

```python
{% raw %}
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
{% endraw %}
```
The IntRegOperand class represents Integer type operand, 
thus it overrides isReg and isIntReg definition.
One operand can be stored in a register or presented as a constant. 
Note that the IntRegOperand represents 
Integer type operand stored in the register.

### Finalize function generates actual code statements for operand
One most important definition provided by the base class is **finalize**. 
Note that all the Operands and its children classes and methods are defined as python syntax.
Therefore, 
we should require a method to convert python representation to 
CPP which can be understandable by the GEM5. 
The finalize definition does this!
Although different version of finalize implementation exists
depending on the operand type,
we will take a look at the finalize of the Operand class. 
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

The finalize method generates mainly two code bloks:
initialization code for operands generated by **makeConstructor**
and code accessing operands such as register read or write 
retrieved by **makeRead and makeWrite**.
Based on the operand type such as source and destination,
either markeRead or makeWrite will be invoked.
As a result, the actual CPP code statement that can access 
the operands will be generated. 
Let's take a look at makeRead and makeWrite definitions 
provided by the IntRegOperand class as an example. 

```python 
 528 class IntRegOperand(Operand):
 ......
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
The above two definitions check whether the current operands type 
matches the type represented by the IntRegOperand class. 
After that, it generates CPP statements 
which allow accesses to the operands and returns the string.

## Populating proper operand class instances 
We now understand GEM5 utilizes various types of operand classes 
to represent different type of operands independent on the architectures.
Then how the each ISA of different architectures can utilize those 
classes to generate the operands initialization code and proper access codes
formatted in CPP syntax? Yeah answer is the finalize method we've seen, but 
where and how can we generate instances of those operand classes? 

### InstObjParams containing all information required for substitutions
Now it is time to go back to InstObjParams again!
```python
451     def defineMicroLoadOp(mnemonic, code, bigCode='',
452                           mem_flags="0", big=True, nonSpec=False,
453                           implicitStack=False):
......
461         # Build up the all register version of this micro op
462         iops = [InstObjParams(name, Name, 'X86ISA::LdStOp',
463                               { "code": code,
464                                 "ea_code": calculateEA,
465                                 "memDataSize": "dataSize" })]
466         if big:
467             iops += [InstObjParams(name, Name + "Big", 'X86ISA::LdStOp',
468                                    { "code": bigCode,
469                                      "ea_code": calculateEA,
470                                      "memDataSize": "dataSize" })]
471         for iop in iops:
472             header_output += MicroLdStOpDeclare.subst(iop)
473             decoder_output += MicroLdStOpConstructor.subst(iop)
474             exec_output += MicroLoadExecute.subst(iop)
475             exec_output += MicroLoadInitiateAcc.subst(iop)
476             exec_output += MicroLoadCompleteAcc.subst(iop)
```

You might remember that InstObjParams is used for substituting the template.
As shown in the code line 461-470 of the defineMicroLoadOp python definition,
it defines iops which is the array of InstObjParams.
After the iops array is populated, it is passed to the 
subst function of each template shown in the line 471-476.
The subst function will replace the microop specific part of the implementation
with the information provided by the passed InstObjParams instance.
Note that the code snippets defined as python dictionary using { } are passed to
the constructor of the InstObjParams python class.
When you look up the code and calculateEA variables of the defineMicroLoadOp definition,
you can easily find that they are code snippets also.
Let's take a look at InstObjParams python class. 

*gem5/src/arch/isa_parser.py*
{% raw %}
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
{% endraw %}
The main purpose of InstObjParams is defining a particular dictionary. 
This dictionary stores all the passed information including class name and 
code snippets, which will be used later in subst definition of template object
to replace microcode specific parts of the microcode implementation template. 
One of the important information managed by the InstObjParams is the operands field (line 1424).
Note that constructor of the InstObjParams instantiate another object called **OperandList**.

### OperandList parses operands from code snippets
The OperandList parses code snippets of microop
and generates **Operand** objects.
Yeah this is one of the location where the Operand objects are populated.
Each Operand provides useful information to
constructor creation and defining multiple definitions required for implementing one microop.
The OperandList can generate Operand classes 
based on the operand keywords specified in the code-snippet. 
Note that OperandList takes second argument of the defineMicroLoadOp definition.

```python 
defineMicroLoadOp('Ld', 'Data = merge(Data, Mem, dataSize);',
```

For example, in the above defineMicroLoadOp invocation, 
'Data = merge(Data, Mem, dataSize);' is passed to the OperandList's constructor 
and stored to the operands field of the InstObjParams (populated in the defineMicroLoadOp).
Note that this code snippet represents microop's input and output operands.
To understand details,
Let's take a look at OperandList python class.

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

OperandList parses code snippets with regular expression.
Whenever a new keyword matches, 
it first checks its cache by invoking find_base definition of the OperandList class. 
If there has been a match, it will returns a proper Operand object 
that can represent the found keyword. 
If there is no matches, it should look up **parser.operandNameMap**
which contains all mappings from specific keyword to 
particular Operand object (1180-1189).
Note that the type of matching keyword can be anything
that can be represented by the classes inheriting *Operand class*.
Whenever, a matching Operand object is found, 
It stores parsed operand to the self.items
through the self.append(op_desc) in line 1189.

After parinsg the operands,
it iterates every parsed operands stored in the self.items
and invokes finalize function of each operand (1249-1250).
The finalize function translates each tokens to a code block that
updates or accesses register
depending on destination, source, and type of the operands. 

### Operand parsing and operandNameMap
When the new keyword is found in the code snippet,
it should look up the operandNameMap 
to find matching Operand object. 
Then where and how the operandNameMap has been initialized 
to contain all required information for mapping keyword to Operand object. 
The answer is on the parsing!

*gem5/src/arch/x86/isa/operands.isa*
{% raw %}
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
...
{% endraw %}

```
As shown in the above operands definition, **def operands**,
each architecture defines operands list
that can be used as operands of instructions. 
Although it could be seen as a function definition in the python,
note that its file extension is not py but isa.
Also, this is not a correct function definition semantics in python.
Yeah parser needs to parse this python like block!

*gem5/src/arch/isa_parser.py*
{% raw %}
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
{% endraw %}

The def operand block is parsed by the isa_parser
as other isa definition.
As shown on the above grammar rule,
when the **def operands** block is found,
it invokes *buildOperandNameMap* function
and generates **operandNameMap**.
As a result, the operandNameMap can provide mapping between
operands keyword to suitable Operand object used
for accessing that operands.
For example, as shown in the above def operands blocks,
Data keyword is translated into IntRegOperand object.

### finalize example. 
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
After all arguments are translated into proper Operand objects,
the finalize definition of those objects should be invoked 
to generate CPP statements. 
Let's take a look at the IntRegOperand object because 
Data keyword is mapped to this Operand object. 
Because the IntRegOperand does not override the finalize method,
the finalize method of the base class (Operand) will be invoked.
As a consequence, either makeRead or makeWrite of the IntRegOperand 
Because the Data keyword is located on the LHS of the statement,
it will be set as destination, and the makeWrite operation 
will be invoked as a result of the finalize. 
Also the generated result will be stored in the op_wb field of the IntRegOperand object.
We will see how this field will replace the template of the Ld micro-load instruction. 
Also, note that other fields such as op_xx are generated in the finalize definition
(op_decl for declaring variables, op_rd for read operations for example).



{% raw %}
```python 
 524 src_reg_constructor = '\n\t_srcRegIdx[_numSrcRegs++] = RegId(%s, %s);'
 525 dst_reg_constructor = '\n\t_destRegIdx[_numDestRegs++] = RegId(%s, %s);'
 526 
 527 
 528 class IntRegOperand(Operand):
 529     reg_class = 'IntRegClass'
 ......
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
 ......
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

As shown in the above code,
the makeWrite definition of the IntRegOperand class also utilize string substitutions. 
The final_val local variable is declared as Integer type because it is IntRegOperand class,
and the self.base_name which is the name of the keyword Data is assigned to the variable. 
After that, by invoking setIntRegOperand function, 
it sets the final_val to the destination register operand 
which can be accessible by the ExecContext (xc). 
The substituted string is returned as a result of finalize method, 
but note that still it is not printed out as CPP statement 
to the automatically generated code yet. 
Yeah! The code has been parsed, produced as the OperandList, and 
stored in the operand field of the **InstObjParams**
Remember that InstObjParams is used to replace generic template 
to generate microcode implementation!

## In a nutshell: generating CPP class for microop
Although we spent a lot of times to cover many details of parser 
such as Template and Operands, the one of the most important goal of this posting is 
understanding how the CPP class associated with one microop 
can be automatically generated. 
In the previous posting, we only found that the getAllocator of the python class 
associated with one microop generates constructor code for initiating 
CPP class defined for the microop. 
However, to implement the CPP class, we also need class definition 
and member functions required to implement semantics of the microop 
in addition to the constructor method of the class. 

### MicroLdStOpDeclare: generating CPP class for micro-load operations 
Although there are several microops related with load operations, 
the skeleton of those microops are same (represented as Template) 
because they have similarities because of the characteristics of the load operation.
First of all, the MicroLdStOpDeclare template is used to generate 
CPP class declaration. 

{% raw %}
```python
def template MicroLdStOpDeclare {{
    class %(class_name)s : public %(base_class)s
    {
      public:
        %(class_name)s(ExtMachInst _machInst,
                const char * instMnem, uint64_t setFlags,
                uint8_t _scale, InstRegIndex _index, InstRegIndex _base,
                uint64_t _disp, InstRegIndex _segment,
                InstRegIndex _data,
                uint8_t _dataSize, uint8_t _addressSize,
                Request::FlagsType _memFlags);

        Fault execute(ExecContext *, Trace::InstRecord *) const;
        Fault initiateAcc(ExecContext *, Trace::InstRecord *) const;
        Fault completeAcc(PacketPtr, ExecContext *, Trace::InstRecord *) const;
    };
}};
```
{% endraw %}

Based on the InstObjParams passed to the defineMicroLoadOp, 
microop specific strings will finish the uncompleted parts of the template.
Note that the generated class also have the constructor 
which we were looking for. 

{% raw %}
```python
271 def template MicroLdStOpConstructor {{
272     %(class_name)s::%(class_name)s(
273             ExtMachInst machInst, const char * instMnem, uint64_t setFlags,
274             uint8_t _scale, InstRegIndex _index, InstRegIndex _base,
275             uint64_t _disp, InstRegIndex _segment,
276             InstRegIndex _data,
277             uint8_t _dataSize, uint8_t _addressSize,
278             Request::FlagsType _memFlags) :
279         %(base_class)s(machInst, "%(mnemonic)s", instMnem, setFlags,
280                 _scale, _index, _base,
281                 _disp, _segment, _data,
282                 _dataSize, _addressSize, _memFlags, %(op_class)s)
283     {
284         %(constructor)s;
285     }
286 }};
```
{% endraw %}

The constructor's implementation itself can be also generated 
with the help of another Template substitution, MicroLdStOpConstructor.


## MicroLoadExecute: template used to implement micro-load operation 
More importantly, in addition to the constructor for the microop, 
each microop should implement several definitions 
to have proper semantics of the microop.  
Let's take a look at the MicroLoadExecute template. 
The definition generated by this template is called **execute**, and 
most of the Ld style microcode implements this function. 
However, depending on the semantics of micro-load instructions,
different implementation of the execute will be populated. 
The different InstObjParams result in different replacement in the template,
and the corresponding implementation will be produced as a consequence. 

```python
{% raw %}
 90 def template MicroLoadExecute {{
 91     Fault %(class_name)s::execute(ExecContext *xc,
 92           Trace::InstRecord *traceData) const
 93     {
{% endraw %}
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
```
The above template contains incomplete code-snippets starting with % keyword. 
When the subst function of the corresponding template object is invoked,
all those uncompleted parts will be replaced.
For this replacement, we built the myDict dictionary.
Note that this myDict initialize itself using the information 
provided by the InstObjParams such as operands field of it.
Therefore, during substitution, if it encounters any keyword 
starting with %, it should refer to myDict to retrieve 
proper replacement for that. 
For example, class_name is provided by the InstObjParams.
Also, op_wb is the CPP statements translated from the keyword Data 
to write back the result to the output register. 
Let's take a look at how the execute function will be implemented after substitution.

*gem5/build/X86/arch/x86/generated/exec-ns.cc.inc*
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

As shown in the Line 19133-19138, 
the CPP statements translated from Data keyword of the code-snippet 
are implemented as a result of replacing op_wb. 

[1]: https://www.dabeaz.com/ply/ply.html
