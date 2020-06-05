---
layout: post
titile: "Microops in GEM5"
categories: GEM5, Microops
---
*/gem5/src/arch/x86/faults.cc*
```cpp
 53 namespace X86ISA
 54 {
 55     void X86FaultBase::invoke(ThreadContext * tc, const StaticInstPtr &inst)
 56     {
 57         if (!FullSystem) {
 58             FaultBase::invoke(tc, inst);
 59             return;
 60         }
 61
 62         PCState pcState = tc->pcState();
 63         Addr pc = pcState.pc();
 64         DPRINTF(Faults, "RIP %#x: vector %d: %s\n",
 65                 pc, vector, describe());
 66         using namespace X86ISAInst::RomLabels;
 67         HandyM5Reg m5reg = tc->readMiscRegNoEffect(MISCREG_M5_REG);
 68         MicroPC entry;
 69         if (m5reg.mode == LongMode) {
 70             if (isSoft()) {
 71                 entry = extern_label_longModeSoftInterrupt;
 72             } else {
 73                 entry = extern_label_longModeInterrupt;
 74             }
 75         } else {
 76             entry = extern_label_legacyModeInterrupt;
 77         }
 78         tc->setIntReg(INTREG_MICRO(1), vector);
 79         tc->setIntReg(INTREG_MICRO(7), pc);
 80         if (errorCode != (uint64_t)(-1)) {
 81             if (m5reg.mode == LongMode) {
 82                 entry = extern_label_longModeInterruptWithError;
 83             } else {
 84                 panic("Legacy mode interrupts with error codes "
 85                         "aren't implementde.\n");
 86             }
 87             // Software interrupts shouldn't have error codes. If one
 88             // does, there would need to be microcode to set it up.
 89             assert(!isSoft());
 90             tc->setIntReg(INTREG_MICRO(15), errorCode);
 91         }
 92         pcState.upc(romMicroPC(entry));
 93         pcState.nupc(romMicroPC(entry) + 1);
 94         tc->pcState(pcState);
 95     }
 96
 97     std::string
 98     X86FaultBase::describe() const
 99     {
100         std::stringstream ss;
101         ccprintf(ss, "%s", mnemonic());
102         if (errorCode != (uint64_t)(-1)) {
103             ccprintf(ss, "(%#x)", errorCode);
104         }
105
106         return ss.str();
107     }
```

*gem5/build/X86/arch/x86/generated/decoder-ns.hh.inc*
```cpp
 4587 namespace RomLabels {
 4588 const static uint64_t label_longModeSoftInterrupt_stackSwitched = 92;
 4589 const static uint64_t label_longModeInterrupt_processDescriptor = 11;
 4590 const static uint64_t label_longModeInterruptWithError_cplStackSwitch = 152;
 4591 const static uint64_t label_longModeInterrupt_istStackSwitch = 28;
 4592 const static uint64_t label_jmpFarWork = 192;
 4593 const static uint64_t label_farJmpSystemDescriptor = 207;
 4594 const static uint64_t label_longModeSoftInterrupt_globalDescriptor = 71;
 4595 const static uint64_t label_farJmpGlobalDescriptor = 199;
 4596 const static uint64_t label_initIntHalt = 186;
 4597 const static uint64_t label_longModeInterruptWithError_istStackSwitch = 150;
 4598 const static uint64_t label_legacyModeInterrupt = 184;
 4599 const static uint64_t label_longModeInterruptWithError_globalDescriptor = 132;
 4600 const static uint64_t label_longModeSoftInterrupt_processDescriptor = 72;
 4601 const static uint64_t label_longModeInterruptWithError = 122;
 4602 const static uint64_t label_farJmpProcessDescriptor = 200;
 4603 const static uint64_t label_longModeSoftInterrupt = 61;
 4604 const static uint64_t label_longModeSoftInterrupt_istStackSwitch = 89;
 4605 const static uint64_t label_longModeInterrupt_globalDescriptor = 10;
 4606 const static uint64_t label_longModeInterrupt_cplStackSwitch = 30;
 4607 const static uint64_t label_longModeInterrupt = 0;
 4608 const static uint64_t label_longModeInterruptWithError_processDescriptor = 133;
 4609 const static uint64_t label_longModeInterruptWithError_stackSwitched = 153;
 4610 const static uint64_t label_longModeInterrupt_stackSwitched = 31;
 4611 const static uint64_t label_longModeSoftInterrupt_cplStackSwitch = 91;
 4612 const static MicroPC extern_label_initIntHalt = 186;
 4613 const static MicroPC extern_label_longModeInterruptWithError = 122;
 4614 const static MicroPC extern_label_longModeInterrupt = 0;
 4615 const static MicroPC extern_label_longModeSoftInterrupt = 61;
 4616 const static MicroPC extern_label_legacyModeInterrupt = 184;
 4617 const static MicroPC extern_label_jmpFarWork = 192;
 4618 }

```

*gem5/src/base/types.hh*
```cpp
136 /**
137  * Address type
138  * This will probably be moved somewhere else in the near future.
139  * This should be at least as big as the biggest address width in use
140  * in the system, which will probably be 64 bits.
141  */
142 typedef uint64_t Addr;
143
144 typedef uint16_t MicroPC;
145
146 static const MicroPC MicroPCRomBit = 1 << (sizeof(MicroPC) * 8 - 1);
147
148 static inline MicroPC
149 romMicroPC(MicroPC upc)
150 {
151     return upc | MicroPCRomBit;
152 }
```

*gem5/src/arch/x86/types.hh*
```cpp
 51 namespace X86ISA
 52 {
 53     //This really determines how many bytes are passed to the decoder.
 54     typedef uint64_t MachInst;

289     class PCState : public GenericISA::UPCState<MachInst>
290     {
291       protected:
292         typedef GenericISA::UPCState<MachInst> Base;
293
294         uint8_t _size;
295
296       public:
297         void
298         set(Addr val)
299         {
300             Base::set(val);
301             _size = 0;
302         }
303
304         PCState() {}
305         PCState(Addr val) { set(val); }
306
307         void
308         setNPC(Addr val)
309         {
310             Base::setNPC(val);
311             _size = 0;
312         }
313
314         uint8_t size() const { return _size; }
315         void size(uint8_t newSize) { _size = newSize; }
316
317         bool
318         branching() const
319         {
320             return (this->npc() != this->pc() + size()) ||
321                    (this->nupc() != this->upc() + 1);
322         }
323
324         void
325         advance()
326         {
327             Base::advance();
328             _size = 0;
329         }
330
331         void
332         uEnd()
333         {
334             Base::uEnd();
335             _size = 0;
336         }
337
338         void
339         serialize(CheckpointOut &cp) const
340         {
341             Base::serialize(cp);
342             SERIALIZE_SCALAR(_size);
343         }
344
345         void
346         unserialize(CheckpointIn &cp)
347         {
348             Base::unserialize(cp);
349             UNSERIALIZE_SCALAR(_size);
350         }
351     };
```

*gem5/src/arch/generic/types.hh*
```cpp
194 template <class MachInst>
195 class UPCState : public SimplePCState<MachInst>
196 {
197   protected:
198     typedef SimplePCState<MachInst> Base;
199
200     MicroPC _upc;
201     MicroPC _nupc;
202
203   public:
204
205     MicroPC upc() const { return _upc; }
206     void upc(MicroPC val) { _upc = val; }
207
208     MicroPC nupc() const { return _nupc; }
209     void nupc(MicroPC val) { _nupc = val; }
210
211     MicroPC
212     microPC() const
213     {
214         return _upc;
215     }
216
217     void
218     set(Addr val)
219     {
220         Base::set(val);
221         upc(0);
222         nupc(1);
223     }
224
225     UPCState() : _upc(0), _nupc(1) {}
226     UPCState(Addr val) : _upc(0), _nupc(0) { set(val); }
227
228     bool
229     branching() const
230     {
231         return this->npc() != this->pc() + sizeof(MachInst) ||
232                this->nupc() != this->upc() + 1;
233     }
234
235     // Advance the upc within the instruction.
236     void
237     uAdvance()
238     {
239         _upc = _nupc;
240         _nupc++;
241     }
242
243     // End the macroop by resetting the upc and advancing the regular pc.
244     void
245     uEnd()
246     {
247         this->advance();
248         _upc = 0;
249         _nupc = 1;
250     }
251
252     bool
253     operator == (const UPCState<MachInst> &opc) const
254     {
255         return Base::_pc == opc._pc &&
256                Base::_npc == opc._npc &&
257                _upc == opc._upc && _nupc == opc._nupc;
258     }
259
260     bool
261     operator != (const UPCState<MachInst> &opc) const
262     {
263         return !(*this == opc);
264     }
265
266     void
267     serialize(CheckpointOut &cp) const override
268     {
269         Base::serialize(cp);
270         SERIALIZE_SCALAR(_upc);
271         SERIALIZE_SCALAR(_nupc);
272     }
273
274     void
275     unserialize(CheckpointIn &cp) override
276     {
277         Base::unserialize(cp);
278         UNSERIALIZE_SCALAR(_upc);
279         UNSERIALIZE_SCALAR(_nupc);
280     }
281 };
```


```cpp
133 /*
134  * Different flavors of PC state. Only ISA specific code should rely on
135  * any particular type of PC state being available. All other code should
136  * use the interface above.
137  */
138
139 // The most basic type of PC.
140 template <class MachInst>
141 class SimplePCState : public PCStateBase
142 {
143   protected:
144     typedef PCStateBase Base;
145
146   public:
147
148     Addr pc() const { return _pc; }
149     void pc(Addr val) { _pc = val; }
150
151     Addr npc() const { return _npc; }
152     void npc(Addr val) { _npc = val; }
153
154     void
155     set(Addr val)
156     {
157         pc(val);
158         npc(val + sizeof(MachInst));
159     };
160
161     void
162     setNPC(Addr val)
163     {
164         npc(val);
165     }
166
167     SimplePCState() {}
168     SimplePCState(Addr val) { set(val); }
169
170     bool
171     branching() const
172     {
173         return this->npc() != this->pc() + sizeof(MachInst);
174     }
175
176     // Advance the PC.
177     void
178     advance()
179     {
180         _pc = _npc;
181         _npc += sizeof(MachInst);
182     }
183 };
```


```cpp
 50 namespace GenericISA
 51 {
 52
 53 // The guaranteed interface.
 54 class PCStateBase : public Serializable
 55 {
 56   protected:
 57     Addr _pc;
 58     Addr _npc;
 59
 60     PCStateBase() : _pc(0), _npc(0) {}
 61     PCStateBase(Addr val) : _pc(0), _npc(0) { set(val); }
 62
 63   public:
 64     /**
 65      * Returns the memory address the bytes of this instruction came from.
 66      *
 67      * @return Memory address of the current instruction's encoding.
 68      */
 69     Addr
 70     instAddr() const
 71     {
 72         return _pc;
 73     }
 74
 75     /**
 76      * Returns the memory address the bytes of the next instruction came from.
 77      *
 78      * @return Memory address of the next instruction's encoding.
 79      */
 80     Addr
 81     nextInstAddr() const
 82     {
 83         return _npc;
 84     }
 85
 86     /**
 87      * Returns the current micropc.
 88      *
 89      * @return The current micropc.
 90      */
 91     MicroPC
 92     microPC() const
 93     {
 94         return 0;
 95     }
 96
 97     /**
 98      * Force this PC to reflect a particular value, resetting all its other
 99      * fields around it. This is useful for in place (re)initialization.
100      *
101      * @param val The value to set the PC to.
102      */
103     void set(Addr val);
104
105     bool
106     operator == (const PCStateBase &opc) const
107     {
108         return _pc == opc._pc && _npc == opc._npc;
109     }
110
111     bool
112     operator != (const PCStateBase &opc) const
113     {
114         return !(*this == opc);
115     }
116
117     void
118     serialize(CheckpointOut &cp) const override
119     {
120         SERIALIZE_SCALAR(_pc);
121         SERIALIZE_SCALAR(_npc);
122     }
123
124     void
125     unserialize(CheckpointIn &cp) override
126     {
127         UNSERIALIZE_SCALAR(_pc);
128         UNSERIALIZE_SCALAR(_npc);
129     }
130 };
```



