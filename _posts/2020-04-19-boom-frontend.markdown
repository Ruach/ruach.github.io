---
layout: post
titile: "What is the frontend and how does it orchestrate different components?"
categories: risc-v, boom
---

The definition of front-end in general includes two big component 
in the very beginning of the pipeline:
The Fetch and Branch Prediction portions of the pipeline that fetch instructions.
Also, to support enhanced fetch and branch prediction,
it needs multiple different components
such as TLB, I-Cache that aids performance of front-end.
In this post, 
we will explore how those components are combined and organized together 
in the Boom Frontend.
To whom wants to understand how the frontend instance is initiated in the boom and 
how the different components of the Boom is connected with the frontend, 
please refer the previous posting. 


**ifu/frontend.scala**
```scala
131 class BoomFrontend(val icacheParams: ICacheParams, hartid: Int)(implicit p: Parameters) extends LazyModule
132 {
133   lazy val module = new BoomFrontendModule(this)
134   val icache = LazyModule(new boom.ifu.ICache(icacheParams, hartid))
135   val masterNode = icache.masterNode
136   val slaveNode = icache.slaveNode
137 }
```
As shown in the above code, BoomFrontend class embeds
ICache module and BoomFrontendModule.
***BoomFrontendModule*** is the most important module 
in the entire Boom fornt-end pipeline.
This module combines fetch-controller, branch-prediction unit, and TLB.
Also, to access the instruction from the ICache,
it makes use of reference to outer instance BoomFrontend
which actually contains ICache module. 

To understand front-end pipeline,
we should focus on the data and operations of each module.
In other words,
which data input is required by which mnodule,
and how the input data is processed and generate result output
should be studied to understand the front-end logic.
Also, because front-end consists of multiple modules
and communicates with the outside logic,
their input/output communication should be clearly uderstood. 
Let's delve into the actual pipeline of front-end logic of the Boom core.

![Boom Frontend Pipeline](/images/front-end.svg)
As shown in the above image, 
frontend of the boom core is pipelined in 5 stages.
The ***FetchControlUnit*** class instatiated by BoomFrontendModule
implements these 5 stages pipeline.
Although the figure describes 
entire fetch pipelines and required components 
such as TLB, BTB, BPD, and ICache 
are embedded in the one giant module,
the actual FetchControlUnit class implementation 
doesn't include those components.
Those auxiliary components are instantiated 
by the BoomFrontendModule and BoomFrontend classes,
and the initiated modules can be referenced
thorugh the outer module instance.

**ifu/frontend.scala**
```scala 
158 class BoomFrontendModule(outer: BoomFrontend) extends LazyModuleImp(outer)
159   with HasCoreParameters
160   with HasL1ICacheParameters
161   with HasL1ICacheBankedParameters
162 {
163   val io = IO(new BoomFrontendBundle(outer))
164   implicit val edge = outer.masterNode.edges.out(0)
165   require(fetchWidth*coreInstBytes == outer.icacheParams.fetchBytes)
166
167   val icache = outer.icache.module
168   val tlb = Module(new TLB(true, log2Ceil(fetchBytes), TLBConfig(nTLBEntries)))
169   val fetch_controller = Module(new FetchControlUnit)
170   val bpdpipeline = Module(new BranchPredictionStage(bankBytes))
171
172   val s0_pc = Wire(UInt(vaddrBitsExtended.W))

237   s0_pc := alignPC(Mux(fetch_controller.io.imem_req.valid, fetch_controller.io.imem_req.bits.pc, npc))
238   fetch_controller.io.imem_resp.valid := RegNext(s1_valid) && s2_valid &&
239                                          (icache.io.resp.valid || !s2_tlb_resp.miss && icache.io.s2_kill)
240   fetch_controller.io.imem_resp.bits.pc := s2_pc
241
242   fetch_controller.io.imem_resp.bits.data := icache.io.resp.bits.data
243   fetch_controller.io.imem_resp.bits.mask := fetchMask(s2_pc)
244
245   fetch_controller.io.imem_resp.bits.replay := icache.io.resp.bits.replay || icache.io.s2_kill &&
246                                                !icache.io.resp.valid && !s2_xcpt
247   fetch_controller.io.imem_resp.bits.btb := s2_btb_resp_bits
248   fetch_controller.io.imem_resp.bits.btb.taken := s2_btb_taken
249   fetch_controller.io.imem_resp.bits.xcpt := s2_tlb_resp
250   when (icache.io.resp.valid && icache.io.resp.bits.ae) { fetch_controller.io.imem_resp.bits.xcpt.ae.inst := true.B }
```
Although F0 stage is implemented inside
the FectchControlUnit module, 
BoomFrontendModule manages the next fetch address *s0_pc*.
This is because *BoomFrontendModule* orchestrates 
not only the front-end pipeline,
but also the other auxiliary modules that require next fetch addres.
The role of the fetch controller is 
examining whether fetch-addresss-redirection is necessary.
As shown in the line 237, 
when the fetch_controller.io.imem_req.valid returns true,
it will redirect the next fetch address to 
fetch_controller.io.imem_req.bits.pc.
On the other hand, 
next pc address (npc) which is (current PC + 4) is used 
as the next fetch address.
Now let's take a look at 
how the FetchControlUnit determines redirection and retrieve the redirection targetr 
thorugh the rest of 5 stages in front-end. 
(How the branch prediction results are derived 
and 
how Icache retrieves the actual instruction bytes 
will be discussed)

**ifu/fetch-control-unit.scala**
```scala
 67 class FetchControlUnit(implicit p: Parameters) extends BoomModule
 68   with HasL1ICacheBankedParameters
 69 {

176   //-------------------------------------------------------------
177   // **** NextPC Select (F0) ****
178   //-------------------------------------------------------------
179
180   val f0_redirect_val =
181     br_unit.take_pc ||
182     io.flush_take_pc ||
183     io.sfence_take_pc ||
184     (io.f2_btb_resp.valid && io.f2_btb_resp.bits.taken && io.imem_resp.ready) ||
185     r_f4_req.valid
186
187   io.imem_req.valid   := f0_redirect_val // tell front-end we had an unexpected change in the stream
188   io.imem_req.bits.pc := f0_redirect_pc
189   io.imem_req.bits.speculative := !(io.flush_take_pc)
190   io.imem_resp.ready  := q_f3_imemresp.io.enq.ready
191
192   f0_redirect_pc :=
193      Mux(io.sfence_take_pc,
194       io.sfence_addr,
195     Mux(ftq.io.take_pc.valid,
196       ftq.io.take_pc.bits.addr,
197     Mux(io.flush_take_pc,
198       io.flush_pc,
199     Mux(br_unit.take_pc,
200       br_unit.target,
201     Mux(r_f4_req.valid,
202       r_f4_req.bits.addr,
203       io.f2_btb_resp.bits.target)))))
```

As shown in the BoomFrontendModule, 
depending on the fetch_controller.io.imem_req.valid signal,
s0_pc (next fetch address) is determined.
To determine the redirection,
it should reflect multiple information derived from
different pipeline stages. 
*f0_redirect_val* is bool type variable
indicating whether the next fetch address should be redirected.
For example, branch, flush, sfence, btb response signals affects redirection.
When redirection is necessary,
*f0_redirect_pc* contains the redirected fetch address.
Multiple cascaded Mux determines the redirected address
dpending on the different redirect signals.
Theses two signals are transferred to the BoomFrontendModule
through the ready-valid interface.

In addition to fetching actual instructions and feed them to the execution unit,
determining the next fecth address is one of the most important job of the front-end. 
Therefore, while we traverse the 5 stage pipelines of front-end,
it is worthwhile to carefully look at
the dependent signals that can affect those two signals 
that can determine redirection.

```scala
205   //-------------------------------------------------------------
206   // **** ICache Access (F1) ****
207   //-------------------------------------------------------------
208
209   // twiddle thumbs
210
```
Interestingly, for the next pipeline stage,
the FetchControlUnit doesn't include any logic for accessing the ICache. 
This is because 
ICache module is included in the BoomFrontend class and 
actual access to the ICache is managed by the BoomFrontendModule class. 
Let's revist the BoomFrontendModule class again 
to take a look at how the frontend access the Icache,
and its result is forwarded to the FetchControlUnit class. 

**ifu/frontend.scala**
```scala
226   icache.io.hartid := io.hartid
227   icache.io.req.valid := s0_valid
228   icache.io.req.bits.addr := s0_pc
229   icache.io.invalidate := io.cpu.flush_icache
230   icache.io.s1_vaddr := s1_pc
231   icache.io.s1_paddr := tlb.io.resp.paddr
232   icache.io.s2_vaddr := s2_pc
233   icache.io.s1_kill := s2_redirect || tlb.io.resp.miss || s2_replay
234   icache.io.s2_kill := s2_speculative && !s2_tlb_resp.cacheable || s2_xcpt
235   icache.io.s2_prefetch := s2_tlb_resp.prefetchable
236
237   s0_pc := alignPC(Mux(fetch_controller.io.imem_req.valid, fetch_controller.io.imem_req.bits.pc, npc))
238   fetch_controller.io.imem_resp.valid := RegNext(s1_valid) && s2_valid &&
239                                          (icache.io.resp.valid || !s2_tlb_resp.miss && icache.io.s2_kill)
240   fetch_controller.io.imem_resp.bits.pc := s2_pc
241
242   fetch_controller.io.imem_resp.bits.data := icache.io.resp.bits.data
243   fetch_controller.io.imem_resp.bits.mask := fetchMask(s2_pc)
244
245   fetch_controller.io.imem_resp.bits.replay := icache.io.resp.bits.replay || icache.io.s2_kill &&
246                                                !icache.io.resp.valid && !s2_xcpt
247   fetch_controller.io.imem_resp.bits.btb := s2_btb_resp_bits
248   fetch_controller.io.imem_resp.bits.btb.taken := s2_btb_taken
249   fetch_controller.io.imem_resp.bits.xcpt := s2_tlb_resp
250   when (icache.io.resp.valid && icache.io.resp.bits.ae) { fetch_controller.io.imem_resp.bits.xcpt.ae.inst := true.B }
```
As shown in the above line 226 to 235,
BoomFrontendModule class sets IO signals 
required for accessing the instruction cache. 
And the result of cache access can be retrieved from 
icache.io.resp.bits.data wire 
which is connected to the fetch_controller.io.imem_resp.bits.data (line 242).
Therefore, without ICache accessing logic in the FetchControlUnit class,
it can access real instruction bytes fetched from the ICache.

**ifu/fetch-control-unit.scala**
```scala
130   val q_f3_imemresp   = withReset(reset.toBool || clear_f3) {
131                           Module(new ElasticReg(gen = new freechips.rocketchip.rocket.FrontendResp)) }
132   val q_f3_btb_resp   = withReset(reset.toBool || clear_f3) { Module(new ElasticReg(gen = Valid(new BoomBTBResp))) }
...
211   //-------------------------------------------------------------
212   // **** ICache Response/Pre-decode (F2) ****
213   //-------------------------------------------------------------
214
215   q_f3_imemresp.io.enq.valid := io.imem_resp.valid
216   q_f3_btb_resp.io.enq.valid := io.imem_resp.valid
217
218   q_f3_imemresp.io.enq.bits := io.imem_resp.bits
219   q_f3_btb_resp.io.enq.bits := io.f2_btb_resp
```
The Boom frontend manages two response queues to keep fetching instructions:
*IMem Response Queue* and *BTB Response Queue*.
Note that the queues only considers the input as valid 
when the io.imem_resp.valid is true
because the queues are declared with *decoupled interface*.
This is because those two reponses can be retrieved 
from outer modules, ICache and BTB.
As shown in the line 238-239 in BoomFrontendModule,
the signal is set on as true 
when the icache and tlb response correctly, and 
s1 and s2 signals are valid. 

The IMem Response Queue can enqueue *FrontendResp* class instances.
The most valuable information in the FronendResp is the data 
fetched from the *ICache*, 
which is the raw bytes of instructions.

**rocket/Frontend.scala**
```scala
 33 class FrontendResp(implicit p: Parameters) extends CoreBundle()(p) {
 34   val btb = new BTBResp
 35   val pc = UInt(width = vaddrBitsExtended)  // ID stage PC
 36   val data = UInt(width = fetchWidth * coreInstBits)
 37   val mask = Bits(width = fetchWidth)
 38   val xcpt = new FrontendExceptions
 39   val replay = Bool()
 40 }
```
The other queue 
stores BTB information called *BoomBTBResp*.
This structure provides valuable branch prediction information
such as the type of branch instruction (cfi_type),
the direction of the branch (taken),
and target address of the branch (address)
retrieved by *BranchPredictionStage*.

**bpu/btb/btb.scala**
```scala 
113 /**
114  * The response packet sent back from the BTB
115  */
116 class BoomBTBResp(implicit p: Parameters) extends BoomBTBBundle
117 {
118   val taken     = Bool()   // is BTB predicting a taken cfi?
119   val target    = UInt(vaddrBits.W) // what target are we predicting?
120
121   // a mask of valid instructions (instructions are
122   //   masked off by the predicted taken branch from the BTB).
123   val mask      = UInt(fetchWidth.W) // mask of valid instructions.
124
125   // the low-order PC bits of the predicted branch (after
126   //   shifting off the lowest log(inst_bytes) bits off).
127   val cfi_idx   = UInt(log2Ceil(fetchWidth).W) // where is cfi we are predicting?
128   val bpd_type  = BpredType() // which predictor should we use?
129   val cfi_type  = UInt(CFI_SZ.W)  // what type of instruction is this?
130   val fetch_pc  = UInt(vaddrBits.W) // the PC we're predicting on (start of the fetch packet).
131
132   val bim_resp  = Valid(new BimResp) // Output from the bimodal table. Valid if prediction provided.
133
134   val is_rvc    = Bool()
135   val is_edge   = Bool()
136 }
```

F3 stage is the most complex stage 
in the front-end pipeline of the Boom.
Although 
the different stages of front-end doesn't split 
into individual modules, 
focusing on input/output of F3 stage (data touched in F3 stage)
and  
operations done on the input
is helpful to understand overall implementation.

**ifu/fetch-control-unit.scala**
```scala
221   //-------------------------------------------------------------
222   // **** F3 ****
223   //-------------------------------------------------------------
224
225   clear_f3 := io.clear_fetchbuffer || r_f4_req.valid
226
227   val f3_imemresp = q_f3_imemresp.io.deq.bits
228   val f3_btb_resp = q_f3_btb_resp.io.deq.bits
229
230   q_f3_imemresp.io.deq.ready := f4_ready
231   q_f3_btb_resp.io.deq.ready := f4_ready
```
As shown before in the F2 stage, 
most important inputs to the F3 stage are 
IMem response queue and BTB response queue.
Because F3 stage consumes the two queues,
it should set the ready signals of the queues
before draining the data.
Then what operations are done on the data
in the F3 stage? 

First, we will take a look at the pre-decode operations 
that discern branch instructions within the fetch packet.
Although current implementations are about fetch pipelines,
it needs to understand what instructions are contained in the fetch packet
before the decode stage comes.
This is because
branch instruction can determine 
if the next fecth address should be redirected.
However, only knowing the branch instruction is inlcuded in the fetch packet
cannot determine the redirection.

```scala
233   // round off to nearest fetch boundary
234   val f3_aligned_pc = alignToFetchBoundary(f3_imemresp.pc)
235   val f3_debug_pcs  = Wire(Vec(fetchWidth, UInt(vaddrBitsExtended.W)))
236   val f3_valid_mask = Wire(Vec(fetchWidth, Bool()))
237   val is_br     = Wire(Vec(fetchWidth, Bool()))
238   val is_jal    = Wire(Vec(fetchWidth, Bool()))
239   val is_jr     = Wire(Vec(fetchWidth, Bool()))
240   val is_call   = Wire(Vec(fetchWidth, Bool()))
241   val is_ret    = Wire(Vec(fetchWidth, Bool()))
242   val is_rvc    = Wire(Vec(fetchWidth, Bool()))
243   val br_targs  = Wire(Vec(fetchWidth, UInt(vaddrBitsExtended.W)))
244   val jal_targs = Wire(Vec(fetchWidth, UInt(vaddrBitsExtended.W)))
245   // catch misaligned jumps -- let backend handle misaligned
246   // branches though since only taken branches are exceptions.
247   val jal_targs_ma = Wire(Vec(fetchWidth, Bool()))
248
249   // Tracks trailing 16b of previous fetch packet
250   val prev_half    = Reg(UInt(coreInstBits.W))
251   // Tracks if last fetchpacket contained a half-inst
252   val prev_is_half = RegInit(false.B)
253
254   assert(fetchWidth >= 4 || !usingCompressed) // Logic gets kind of annoying with fetchWidth = 2
255   for (i <- 0 until fetchWidth) {
256     val bpd_decoder = Module(new BranchDecode)
257     val is_valid = Wire(Bool())
258     val inst = Wire(UInt((2*coreInstBits).W))
259     if (!usingCompressed) {
260       is_valid := true.B
261       inst     := f3_imemresp.data(i*coreInstBits+coreInstBits-1,i*coreInstBits)
262       f3_fetch_bundle.edge_inst := false.B
263     } else if (i == 0) {
264       when (prev_is_half) {
265         inst := Cat(f3_imemresp.data(15,0), prev_half)
266         f3_fetch_bundle.edge_inst := true.B
267       } .otherwise {
268         inst := f3_imemresp.data(31,0)
269         f3_fetch_bundle.edge_inst := false.B
270       }
271       is_valid := true.B
272     } else if (i == 1) {
273       // Need special case since 0th instruction may carry over the wrap around
274       inst     := f3_imemresp.data(i*coreInstBits+2*coreInstBits-1,i*coreInstBits)
275       is_valid := prev_is_half || !(f3_valid_mask(i-1) && f3_fetch_bundle.insts(i-1)(1,0) === 3.U)
276     } else if (icIsBanked && i == (fetchWidth / 2) - 1) {
277       // If we are using a banked I$ we could get cut-off halfway through the fetch bundle
278       inst     := f3_imemresp.data(i*coreInstBits+2*coreInstBits-1,i*coreInstBits)
279       is_valid := !(f3_valid_mask(i-1) && f3_fetch_bundle.insts(i-1)(1,0) === 3.U) &&
280                   !(inst(1,0) === 3.U && !f3_imemresp.mask(i+1))
281     } else if (i == fetchWidth - 1) {
282       inst     := Cat(0.U(16.W), f3_imemresp.data(fetchWidth*coreInstBits-1,i*coreInstBits))
283       is_valid := !((f3_valid_mask(i-1) && f3_fetch_bundle.insts(i-1)(1,0) === 3.U) ||
284                     inst(1,0) === 3.U)
285     } else {
286       inst     := f3_imemresp.data(i*coreInstBits+2*coreInstBits-1,i*coreInstBits)
287       is_valid := !(f3_valid_mask(i-1) && f3_fetch_bundle.insts(i-1)(1,0) === 3.U)
288     }
289     f3_fetch_bundle.insts(i) := inst
290
291     // TODO do not compute a vector of targets
292     val pc = (f3_aligned_pc
293             + (i << log2Ceil(coreInstBytes)).U
294             - Mux(prev_is_half && (i == 0).B, 2.U, 0.U))
295     f3_debug_pcs(i) := pc
296
297     val exp_inst = ExpandRVC(inst)
298
299     bpd_decoder.io.inst := exp_inst
300     bpd_decoder.io.pc   := pc
301
302     f3_fetch_bundle.exp_insts(i) := exp_inst
303
304     f3_valid_mask(i) := f3_valid && f3_imemresp.mask(i) && is_valid
305     is_br(i)     := f3_valid && bpd_decoder.io.is_br   && f3_imemresp.mask(i) && is_valid
306     is_jal(i)    := f3_valid && bpd_decoder.io.is_jal  && f3_imemresp.mask(i) && is_valid
307     is_jr(i)     := f3_valid && bpd_decoder.io.is_jalr && f3_imemresp.mask(i) && is_valid
308     is_call(i)   := f3_valid && bpd_decoder.io.is_call && f3_imemresp.mask(i) && is_valid
309     is_ret(i)    := f3_valid && bpd_decoder.io.is_ret  && f3_imemresp.mask(i) && is_valid
310     is_rvc(i)    := f3_valid_mask(i) && inst(1,0) =/= 3.U && usingCompressed.B
311     br_targs(i)  := bpd_decoder.io.target
312     jal_targs(i) := bpd_decoder.io.target
313     jal_targs_ma(i) := jal_targs(i)(1) && is_jal(i) && !usingCompressed.B
314   }
```

Line 255-314 initiates BranchDecode modules 
and provides instructions fetched from the Imem response queue. 
Note that the fetchWidth denotes number of instructions fetched by once
by the front-end pipeline. 
Here, the for loop initiates fetchWidth BranchDecode modules
to pre-decode instructions in parallel.
Although the variables declared in line 256-258 looks single instances
shared among multiple instruction decoding,
chisel initiates fetchWidth modules and wires 
that are not shared.
The actual pre-decode operation is done by the BranchDecode module. 

**exu/decode.scala**
```scala
584 /**
585  * Smaller Decode unit for the Frontend to decode different
586  * branches.
587  * Accepts EXPANDED RVC instructions
588  */
589
590 class BranchDecode(implicit p: Parameters) extends BoomModule
591 {
592   val io = IO(new Bundle {
593     val inst    = Input(UInt(32.W))
594     val pc      = Input(UInt(vaddrBitsExtended.W))
595     val is_br   = Output(Bool())
596     val is_jal  = Output(Bool())
597     val is_jalr = Output(Bool())
598     val is_ret  = Output(Bool())
599     val is_call = Output(Bool())
600     val target = Output(UInt(vaddrBitsExtended.W))
601     val cfi_type = Output(UInt(CFI_SZ.W))
602   })
603
604   val bpd_csignals =
605     freechips.rocketchip.rocket.DecodeLogic(io.inst,
606                   List[BitPat](N, N, N, IS_X),
607 ////                      //   is br?
608 ////                      //   |  is jal?
609 ////                      //   |  |  is jalr?
610 ////                      //   |  |  |  br type
611 ////                      //   |  |  |  |
612             Array[(BitPat, List[BitPat])](
613                JAL     -> List(N, Y, N, IS_J),
614                JALR    -> List(N, N, Y, IS_I),
615                BEQ     -> List(Y, N, N, IS_B),
616                BNE     -> List(Y, N, N, IS_B),
617                BGE     -> List(Y, N, N, IS_B),
618                BGEU    -> List(Y, N, N, IS_B),
619                BLT     -> List(Y, N, N, IS_B),
620                BLTU    -> List(Y, N, N, IS_B)
621             ))
622
623   val (cs_is_br: Bool) :: (cs_is_jal: Bool) :: (cs_is_jalr:Bool) :: imm_sel_ :: Nil = bpd_csignals
624
625   io.is_br   := cs_is_br
626   io.is_jal  := cs_is_jal
627   io.is_jalr := cs_is_jalr
628   io.is_call := (cs_is_jal || cs_is_jalr) && GetRd(io.inst) === RA
629   io.is_ret  := cs_is_jalr && GetRs1(io.inst) === BitPat("b00?01")
630
631   io.target := Mux(cs_is_br, ComputeBranchTarget(io.pc, io.inst, xLen),
632                               ComputeJALTarget(io.pc, io.inst, xLen))
633   io.cfi_type :=
634     Mux(cs_is_jalr,
635       CFI_JALR,
636     Mux(cs_is_jal,
637       CFI_JAL,
638     Mux(cs_is_br,
639       CFI_BR,
640       CFI_X)))
641 }
```

The BranchDecode module gets 
instruction bytes to decode and its address(PC)
to decode branch instruction and 
compute the target address of branch instruction.
Although all branch instructions cannot be fully executed
at this moment,
front-end can easliy retrieve 
target address and taken/not-taken information
of some branch instructions
such as XXX

However, 
because pre-decode stage can only provide 
branch information retrieved from static instruction bytes,
it is hard to know
the direction of the branch (taken/not-taken) and 
target address at this moment.
Those information can be retireved only 
after reading the register and 
executing instruction. 
Therefore, 
Boom architecture relies on the branch prediction.

For branch predictior, 
there are always tradeoff in between
complexity and accuracy.
The Boom Core tries to get the best of both worlds
by adopting two branch predictors, BTB and BPD.
The simplest version of branch predictor 
is Next Line Predictor (NLP).
NLP makes use of Bi-Modal table, BTB, Return Address Stack(RAS) 
and simply represented as BTB.
Complex but accurate version is Backing Predictor (BPD).
BPD makes use of global branch history for prediction.
Let's take a loot at how the BPD and BTB information are utilized in F3 stage.


```scala
315
316   // Does the BPD have a prediction to make (in the case of a BTB miss?)
317   // Calculate in F3 but don't redirect until F4.
318   io.f3_is_br := is_br
319   val f3_bpd_predictions = is_br.asUInt & io.f3_bpd_resp.bits.takens
320   val f3_bpd_br_taken = f3_bpd_predictions.orR
321   val f3_bpd_br_idx = PriorityEncoder(f3_bpd_predictions)
322   val f3_bpd_target = br_targs(f3_bpd_br_idx)
323   // check for jumps -- if we decide to override a taken BTB and choose "nextline" we don't want to miss the JAL.
324   val f3_has_jal = is_jal.reduce(_|_)
325   val f3_jal_idx = PriorityEncoder(is_jal.asUInt)
326   val f3_jal_target = jal_targs(f3_jal_idx)
327
328   val f3_jr_idx = PriorityEncoder(is_jr)
329   val f3_jr_valid = is_jr.reduce(_||_)
330
331   val f3_bpd_btb_update_valid = WireInit(false.B) // does the BPD's choice cause a BTB update?
332   val f3_bpd_may_redirect_taken = WireInit(false.B) // request towards a taken branch target
333   val f3_bpd_may_redirect_next = WireInit(false.B) // override taken prediction and fetch the next line (or take JAL)
334   val f3_bpd_may_redirect = f3_bpd_may_redirect_taken || f3_bpd_may_redirect_next
335   val f3_bpd_redirect_cfiidx =
336     Mux(f3_bpd_may_redirect_taken,
337       f3_bpd_br_idx,
338     Mux(f3_has_jal,
339       f3_jal_idx,
340       (fetchWidth-1).U))
341   val f3_bpd_redirect_target =
342     Mux(f3_bpd_may_redirect_taken,
343       f3_bpd_target,
344     Mux(f3_has_jal,
345       f3_jal_target,
346       nextFetchStart(f3_aligned_pc)))
347
348   // mask out instructions after predicted branch
349   val f3_kill_mask = Wire(UInt(fetchWidth.W))
350   val f3_btb_mask = Wire(UInt(fetchWidth.W))
```

Compared to BTB response accessible in F2 stage,
BPD response can be retireved after F3 stage 
because BpdPredictionStage takes one more cycle
to generate the prediction. 
Also, compared to the BTB response,
BPD response provides very limited branch information
such as branch direction.
Therefore, when the F3 stage follows BPD prediction,
it should makes use of pre-decoded information 
and BTB response 
to figure out branch type and target address. 

This is off-topic a bit, but 
to understnad the implementation, we should understand how the 
chisel convert one data type to the other conveniently.
First of all, when we look at the line 319
*is_br* which is Bool type vector 
is converted into single UInt data.
Chisel automatically convert each Bool data stored in the vector 
and 
form one UInt data 
by concatenating multiple Bool-to-UInt transformed data.
For example, if the vector stores 
[true, true, false]
in descending order index
then it will be tranformed as *b110.U*.
The tranferred value is ANDed with *io.f3_bpd_resp.bits.takens*,
which finds out predicted taken branch exist in the fetched packet.


```scala
135   val f3_valid        = q_f3_imemresp.io.deq.valid
...
365   when (f3_valid && f3_btb_resp.valid) {
366     // btb made a prediction
367     // Make a redirect request if:
368     //    - the BPD (br) comes earlier than the BTB's redirection.
369     //    - If both the BTB and the BPD predicted a branch, the BPD wins (if disagree).
370     //       * involves refetching the next cacheline and undoing the current packet's mask if we "undo" the BT's
371     //       taken branch.
372
373     val btb_idx = f3_btb_resp.bits.cfi_idx
374
375     when (BpredType.isAlwaysTaken(f3_btb_resp.bits.bpd_type)) {
376       f3_bpd_may_redirect_taken := io.f3_bpd_resp.valid && f3_bpd_br_taken && f3_bpd_br_idx < btb_idx
377
378       assert (f3_btb_resp.bits.taken)
379     } .elsewhen (f3_btb_resp.bits.taken) {
380       // does the bpd predict the branch is taken too? (assuming bpd_valid)
381       val bpd_agrees_with_btb = f3_bpd_predictions(btb_idx)
382       f3_bpd_may_redirect_taken := io.f3_bpd_resp.valid && f3_bpd_br_taken &&
383         (f3_bpd_br_idx < btb_idx || !bpd_agrees_with_btb)
384       f3_bpd_may_redirect_next := io.f3_bpd_resp.valid && !f3_bpd_br_taken
385
386       assert (BpredType.isBranch(f3_btb_resp.bits.bpd_type))
387     } .elsewhen (!f3_btb_resp.bits.taken) {
388       f3_bpd_may_redirect_taken := io.f3_bpd_resp.valid && f3_bpd_br_taken
389     }
390   } .otherwise {
391     // BTB made no prediction - let the BPD do what it wants
392     f3_bpd_may_redirect_taken := io.f3_bpd_resp.valid && f3_bpd_br_taken
393     // add branch to the BTB if we think it will be taken
394     f3_bpd_btb_update_valid := f3_bpd_may_redirect_taken
395   }
396
397   assert (PopCount(VecInit(f3_bpd_may_redirect_taken, f3_bpd_may_redirect_next)) <= 1.U,
398     "[bpd_pipeline] mutually-exclusive signals firing")
```

To determine redirection, first of all, 
it should validate whether the branch has been predicted
by BTB or BPD
regardless of its validity about taken/not-taken.
If the branch has been found,
it should be redirected only when the branch is predicted as taken.
Note that redirection is determined speculatively 
because front-end cannot know 
whether the branch will be actually taken or not taken 
at the end of the execution pipeline. 



```scala
400   // catch any BTB mispredictions (and fix-up missed JALs)
401   bchecker.io.valid := f3_valid
402   bchecker.io.inst_mask := VecInit(f3_imemresp.mask.asBools)
403   bchecker.io.is_br  := is_br
404   bchecker.io.is_jal := is_jal
405   bchecker.io.is_jr  := is_jr
406   bchecker.io.is_call  := is_call
407   bchecker.io.is_ret   := is_ret
408   bchecker.io.is_rvc   := is_rvc
409   bchecker.io.edge_inst := f3_fetch_bundle.edge_inst
410   bchecker.io.br_targs := br_targs
411   bchecker.io.jal_targs := jal_targs
412   bchecker.io.fetch_pc := f3_imemresp.pc
413   bchecker.io.aligned_pc := f3_aligned_pc
414   bchecker.io.btb_resp := f3_btb_resp
415   bchecker.io.bpd_resp := io.f3_bpd_resp
```


**ifu/branch-checker.scala**
```scala
 32 /**
 33  * Combinational logic to verify that the BoomBTB predicted correctly. This chooses
 34  * between the BrPredictor or the BoomBTB. Also catch JALs.
 35  */
 36 class BranchChecker(implicit p: Parameters) extends BoomModule
 37   with HasL1ICacheBankedParameters
 38 {
 39   val io = IO(new Bundle {
 40     val req           = Valid(new PCReq)
 41
 42     val valid         = Input(Bool())                   // are the inputs valid?
 43     val inst_mask     = Input(Vec(fetchWidth, Bool())) // valid instruction mask from I$
 44     val is_br         = Input(Vec(fetchWidth, Bool()))
 45     val is_jal        = Input(Vec(fetchWidth, Bool()))
 46     val is_jr         = Input(Vec(fetchWidth, Bool()))
 47     val is_call       = Input(Vec(fetchWidth, Bool()))
 48     val is_ret        = Input(Vec(fetchWidth, Bool()))
 49     val is_rvc        = Input(Vec(fetchWidth, Bool()))
 50     val br_targs      = Input(Vec(fetchWidth, UInt(vaddrBitsExtended.W)))
 51     val jal_targs     = Input(Vec(fetchWidth, UInt(vaddrBitsExtended.W)))
 52
 53     val edge_inst     = Input(Bool())
 54
 55     val fetch_pc      = Input(UInt(vaddrBitsExtended.W))
 56     val aligned_pc    = Input(UInt(vaddrBitsExtended.W))
 57
 58     val btb_resp      = Flipped(Valid(new BoomBTBResp))
 59     val bpd_resp      = Flipped(Valid(new BpdResp))
 60
 61     val btb_update    = Valid(new BoomBTBUpdate)
 62     val ras_update    = Valid(new RasUpdate)
 63
 64     val req_cfi_idx   = Output(UInt(log2Ceil(fetchWidth).W)) // where is cfi we are predicting?
 65   })
 66
 67   // Did the BTB mispredict the cfi type?
 68   // Did the BTB mispredict the cfi target?
 69   // Did the BTB predict a masked-off instruction?
 70   val wrong_cfi = WireInit(false.B)
 71   val wrong_target = WireInit(false.B)
 72
 73   val btb_idx = io.btb_resp.bits.cfi_idx
 74   val btb_target = io.btb_resp.bits.target
 75   val bpd_predicted_taken = io.bpd_resp.valid && io.bpd_resp.bits.takens(io.btb_resp.bits.cfi_idx)
 76
 77   when (io.btb_resp.valid) {
 78     when (io.btb_resp.bits.cfi_type === CFI_BR && (io.btb_resp.bits.taken || bpd_predicted_taken)) {
 79       wrong_cfi := !io.is_br(btb_idx)
 80       wrong_target := io.br_targs(btb_idx) =/= btb_target
 81     } .elsewhen (io.btb_resp.bits.cfi_type === CFI_JAL) {
 82       wrong_cfi := !io.is_jal(btb_idx)
 83       wrong_target := io.jal_targs(btb_idx) =/= btb_target
 84     } .elsewhen (io.btb_resp.bits.cfi_type === CFI_JALR) {
 85       wrong_cfi := !io.is_jr(btb_idx)
 86     } .otherwise {
 87       wrong_cfi := io.btb_resp.bits.cfi_type === CFI_X && io.btb_resp.bits.taken
 88       when (io.valid) {
 89         assert (io.btb_resp.bits.cfi_type =/= CFI_X, "[fetch] predicted on a non-cfi type.")
 90       }
 91     }
 92   }
```

The BranchChecker module makes use of pre-decoded information 
to figure out the branch has been correctly predicted. 
Especailly, as shown in Line 72-92,
the module figures out 
branch traget and branch type has been correctly predicted.
Note that 
pre-decode stage cannot retrieve
target addres for jalr 
which requires register read to calculate target address, so 
it cannot validate whether the target has been correctly predicted. 



 93
 94   val nextline_pc = nextFetchStart(io.aligned_pc)
 95
 96   val btb_was_wrong = io.btb_resp.valid && (wrong_cfi || wrong_target || !io.inst_mask(btb_idx))
 97
 98   val jal_idx = PriorityEncoder(io.is_jal.asUInt)
 99   val btb_hit  = io.btb_resp.valid
100   val jal_wins = io.is_jal.reduce(_|_) &&
101                  (!btb_hit ||
102                  btb_was_wrong ||
103                  (jal_idx < btb_idx) ||
104                  !io.btb_resp.bits.taken)
105
106   //-------------------------------------------------------------
107   // Perform redirection
108
109   // Redirect if:
110   //    - JAL comes before BTB's cfi_idx
111   //       * kill everything behind JAL -- including BTB's predinfo
112   //    - BTB was wrong
113   //       * if JAL, take JAL (if valid instructions available)
114   //       * if !JAL, request nextline (set all masks to valid).
115   //    - No JAL, BTB correct
116   //       * do nothing
117
118   io.req.valid := jal_wins || btb_was_wrong
119   io.req.bits.addr := Mux(jal_wins, io.jal_targs(jal_idx), nextline_pc)
120   // Help mask out instructions after predicted cfi.
121   io.req_cfi_idx := Mux(jal_wins, jal_idx, (fetchWidth-1).U)
122
123
124   //-------------------------------------------------------------
125   // Perform updates
126
127   // update the BTB for jumps it missed.
128   // TODO XXX also allow us to clear bad BTB entries when btb is wrong.
129   io.btb_update.valid         := jal_wins
130   io.btb_update.bits.pc       := io.fetch_pc
131   io.btb_update.bits.target   := io.jal_targs(jal_idx)
132   io.btb_update.bits.taken    := true.B
133   io.btb_update.bits.cfi_idx  := jal_idx
134   io.btb_update.bits.bpd_type := Mux(io.is_call(jal_idx), BpredType.CALL, BpredType.JUMP)
135   io.btb_update.bits.cfi_type := CFI_JAL
136   io.btb_update.bits.is_rvc   := io.is_rvc(jal_idx)
137   io.btb_update.bits.is_edge  := io.edge_inst && (jal_idx === 0.U)
138
139   // for critical path reasons, remove dependence on bpu_request to ras_update.
140   val jal_may_win = io.is_jal.reduce(_|_) && (!btb_hit || btb_was_wrong || jal_idx < btb_idx)
141   io.ras_update.valid := jal_may_win && io.is_call(jal_idx)
142   io.ras_update.bits.is_call     := true.B
143   io.ras_update.bits.is_ret      := false.B
144   io.ras_update.bits.return_addr := (io.aligned_pc
145                                     + (jal_idx << log2Ceil(coreInstBytes))
146                                     + Mux(io.is_rvc(jal_idx), 2.U, 4.U))
147 }
```

```scala
416
417   // who wins? bchecker or bpd?
418   val jal_overrides_bpd = f3_has_jal && f3_jal_idx < f3_bpd_redirect_cfiidx && f3_bpd_may_redirect_taken
419   val f3_bpd_overrides_bcheck = f3_bpd_may_redirect && !jal_overrides_bpd &&
420                                 (!bchecker.io.req.valid || f3_bpd_redirect_cfiidx < bchecker.io.req_cfi_idx)
421   f3_req.valid := f3_valid && (f3_bpd_may_redirect && !jal_overrides_bpd || bchecker.io.req.valid)
422   f3_req.bits.addr := Mux(f3_bpd_overrides_bcheck, f3_bpd_redirect_target, bchecker.io.req.bits.addr)
423
424   // This has a bad effect on QoR.
425   io.f3_will_redirect := false.B //f3_req.valid
426
427   val f3_btb_update_bits = Wire(new BoomBTBUpdate)
428   val f3_btb_update_valid = Mux(f3_bpd_overrides_bcheck,
429                               f3_bpd_btb_update_valid      && (!f3_jr_valid || f3_bpd_br_idx < f3_jr_idx),
430                               bchecker.io.btb_update.valid && (!f3_jr_valid || f3_jal_idx    < f3_jr_idx))
431   io.f3_btb_update.valid := RegNext(f3_btb_update_valid) && r_f4_req.valid
432   io.f3_btb_update.bits := RegNext(f3_btb_update_bits)
433   f3_btb_update_bits := bchecker.io.btb_update.bits
434   when (f3_bpd_overrides_bcheck) {
435     f3_btb_update_bits.target   := f3_bpd_target
436     f3_btb_update_bits.cfi_idx  := f3_bpd_br_idx
437     f3_btb_update_bits.bpd_type := BpredType.BRANCH
438     f3_btb_update_bits.cfi_type := CFI_BR
439     f3_btb_update_bits.is_rvc   := is_rvc(f3_bpd_br_idx)
440     f3_btb_update_bits.is_edge  := f3_fetch_bundle.edge_inst && (f3_bpd_br_idx === 0.U)
441   }
442
443   io.f3_ras_update := bchecker.io.ras_update
444
445   f3_kill_mask := KillMask(
446     f3_req.valid,
447     Mux(f3_bpd_overrides_bcheck, f3_bpd_redirect_cfiidx, bchecker.io.req_cfi_idx),
448     fetchWidth)
449
450   f3_btb_mask := Mux(f3_btb_resp.valid && !f3_req.valid,
451                    f3_btb_resp.bits.mask,
452                    Fill(fetchWidth, 1.U(1.W)))
453   f3_fetch_bundle.mask := (~f3_kill_mask
454                           & f3_btb_mask
455                           & f3_valid_mask.asUInt)
456
457   val f3_taken = WireInit(false.B) // was a branch taken in the F3 stage?
458   when (f3_req.valid) {
459     // f3_bpd only requests taken redirections on btb misses.
460     // f3_req via bchecker only ever requests nextline_pc or jump targets (which we don't track in ghistory).
461     f3_taken := f3_bpd_overrides_bcheck && f3_bpd_may_redirect_taken
462   } .elsewhen (f3_btb_resp.valid) {
463     f3_taken := f3_btb_resp.bits.taken
464   }
465
466   f3_fetch_bundle.pc := f3_imemresp.pc
467   f3_fetch_bundle.ftq_idx := ftq.io.enq_idx
468   f3_fetch_bundle.xcpt_pf_if := f3_imemresp.xcpt.pf.inst
469   f3_fetch_bundle.xcpt_ae_if := f3_imemresp.xcpt.ae.inst
470   f3_fetch_bundle.replay_if :=  f3_imemresp.replay
471   f3_fetch_bundle.xcpt_ma_if_oh := jal_targs_ma.asUInt
472
473   for (w <- 0 until fetchWidth) {
474     f3_fetch_bundle.debug_events(w).fetch_seq := DontCare
475   }
476
477   for (w <- 0 until fetchWidth) {
478     f3_fetch_bundle.bpu_info(w).btb_blame     := false.B
479     f3_fetch_bundle.bpu_info(w).btb_hit       := f3_btb_resp.valid
480     f3_fetch_bundle.bpu_info(w).btb_taken     := false.B
481
482     f3_fetch_bundle.bpu_info(w).bpd_blame     := false.B
483     f3_fetch_bundle.bpu_info(w).bpd_hit       := io.f3_bpd_resp.valid
484     f3_fetch_bundle.bpu_info(w).bpd_taken     := io.f3_bpd_resp.bits.takens(w.U)
485     f3_fetch_bundle.bpu_info(w).bim_resp      := f3_btb_resp.bits.bim_resp.bits
486     f3_fetch_bundle.bpu_info(w).bpd_resp      := io.f3_bpd_resp.bits
487
488     when (w.U === f3_bpd_br_idx && f3_bpd_overrides_bcheck) {
489       f3_fetch_bundle.bpu_info(w).bpd_blame := true.B
490     } .elsewhen (w.U === f3_btb_resp.bits.cfi_idx && f3_btb_resp.valid && !f3_req.valid) {
491        f3_fetch_bundle.bpu_info(w).btb_blame := true.B
492     }
493
494     when (w.U === f3_btb_resp.bits.cfi_idx && f3_btb_resp.valid) {
495       f3_fetch_bundle.bpu_info(w).btb_taken := f3_btb_resp.bits.taken
496     }
497   }
```
