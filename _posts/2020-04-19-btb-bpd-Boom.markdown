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
are embedded in the front end pipeline,
the actual FetchControlUnit class implementation 
doesn't include those components.
Those auxiliary components are instantiated 
by the BoomFrontendModule and BoomFrontend class
and the modules can be referenced
thorugh the outer module instance.

This is because the modules are not only accessed by the front-end pipeline,
but also utilized by the different pipelines of Boom core.
Therefore, 
instead of embedding the Icache instance 
directly from the FetchControlUnit class,
it receives the valid signal and data inputs from the Icache module
managed by the upper layer module, the BoomFrontendModule class. 

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
The *fetch_controller* member in the BoomFrontendModule
is the instance of FetchControlUnit class.
As fetch_controller instacne determines next fetch-pc address,
s0_pc is determined based on the signal sent from the fetch_controller.
When the fetch_controller.io.imem_req.valid signal is true,
then the new address determined by the fetch_controller should be used
to fetch instructions from the icache.
On the other hand, next pc address (npc) is used. 
Now let's take a look at the implementation of 5 stages of front-end. 


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
193     Mux(io.sfence_take_pc,
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
As shown in the above code,
depending on the multiple different redirection events
(branch, flush, sfence, btb response??),
the next pc address should be redirected.

```scala
205   //-------------------------------------------------------------
206   // **** ICache Access (F1) ****
207   //-------------------------------------------------------------
208
209   // twiddle thumbs
210
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

```scala
252   //-------------------------------------------------------------
253   // **** Fetch Controller ****
254   //-------------------------------------------------------------
255
256   fetch_controller.io.br_unit           := io.cpu.br_unit
257   fetch_controller.io.tsc_reg           := io.cpu.tsc_reg
258
259   fetch_controller.io.status            := io.cpu.status
260   fetch_controller.io.bp                := io.cpu.bp
261
262   fetch_controller.io.f2_btb_resp       := bpdpipeline.io.f2_btb_resp
263   fetch_controller.io.f3_bpd_resp       := bpdpipeline.io.f3_bpd_resp
264   fetch_controller.io.f2_bpd_resp       := DontCare
265
266   fetch_controller.io.clear_fetchbuffer := io.cpu.clear_fetchbuffer
267
268   fetch_controller.io.sfence_take_pc    := io.cpu.sfence_take_pc
269   fetch_controller.io.sfence_addr       := io.cpu.sfence_addr
270
271   fetch_controller.io.flush_take_pc     := io.cpu.flush_take_pc
272   fetch_controller.io.flush_pc          := io.cpu.flush_pc
273   fetch_controller.io.com_ftq_idx       := io.cpu.com_ftq_idx
274
275   fetch_controller.io.flush_info        := io.cpu.flush_info
276   fetch_controller.io.commit            := io.cpu.commit
277
278   io.cpu.get_pc <> fetch_controller.io.get_pc
279
280   io.cpu.com_fetch_pc := fetch_controller.io.com_fetch_pc
281
282   io.cpu.fetchpacket <> fetch_controller.io.fetchpacket
```

The s0_pc address determines the next fetch address in the frontend.
When the 

```scala
284   //-------------------------------------------------------------
285   // **** Branch Prediction ****
286   //-------------------------------------------------------------
287
288   bpdpipeline.io.s0_req.valid := s0_valid
289   bpdpipeline.io.s0_req.bits.addr := s0_pc
290
291   bpdpipeline.io.f2_replay := s2_replay
292   bpdpipeline.io.f2_stall := !fetch_controller.io.imem_resp.ready
293   bpdpipeline.io.f3_stall := fetch_controller.io.f3_stall
294   bpdpipeline.io.f3_is_br := fetch_controller.io.f3_is_br
295   bpdpipeline.io.debug_imemresp_pc := fetch_controller.io.imem_resp.bits.pc
296
297   bpdpipeline.io.br_unit_resp := io.cpu.br_unit
298   bpdpipeline.io.ftq_restore := fetch_controller.io.ftq_restore_history
299   bpdpipeline.io.redirect := fetch_controller.io.imem_req.valid
300
301   bpdpipeline.io.flush := io.cpu.flush
302
303   bpdpipeline.io.f2_valid := fetch_controller.io.imem_resp.valid
304   bpdpipeline.io.f2_redirect := fetch_controller.io.f2_redirect
305   bpdpipeline.io.f3_will_redirect := fetch_controller.io.f3_will_redirect
306   bpdpipeline.io.f4_redirect := fetch_controller.io.f4_redirect
307   bpdpipeline.io.f4_taken := fetch_controller.io.f4_taken
308   bpdpipeline.io.fe_clear := fetch_controller.io.clear_fetchbuffer
309
310   bpdpipeline.io.f2_aligned_pc := alignToFetchBoundary(s2_pc)
311   bpdpipeline.io.f3_ras_update := fetch_controller.io.f3_ras_update
312   bpdpipeline.io.f3_btb_update := fetch_controller.io.f3_btb_update
313   bpdpipeline.io.bim_update    := fetch_controller.io.bim_update
314   bpdpipeline.io.bpd_update    := fetch_controller.io.bpd_update
315
316   bpdpipeline.io.status_prv    := io.cpu.status_prv
317   bpdpipeline.io.status_debug  := io.cpu.status_debug
```

**bpu/bpd-pipeline.scala**
```scala
 53 /**
 54  * Wraps the BoomBTB and BrPredictor into a pipeline that is parallel with the Fetch pipeline.
 55  */
 56 class BranchPredictionStage(val bankBytes: Int)(implicit p: Parameters) extends BoomModule
 57 {
 58   val io = IO(new BoomBundle {
 59     // Fetch0
 60     val s0_req            = Flipped(Valid(new freechips.rocketchip.rocket.BTBReq))
 61     val debug_imemresp_pc = Input(UInt(vaddrBitsExtended.W)) // For debug -- make sure I$ and BTB are synchronised.
 62
 63     // Fetch1
 64
 65     // Fetch2
 66     val f2_valid      = Input(Bool()) // f2 stage may proceed into the f3 stage.
 67     val f2_btb_resp   = Valid(new BoomBTBResp)
 68     val f2_stall      = Input(Bool()) // f3 is not ready -- back-pressure the f2 stage.
 69     val f2_replay     = Input(Bool()) // I$ is replaying S2 PC into S0 again (S2 backed up or failed).
 70     val f2_redirect   = Input(Bool()) // I$ is being redirected from F2.
 71     val f2_aligned_pc = Input(UInt(vaddrBitsExtended.W))
 72
 73     // Fetch3
 74     val f3_is_br      = Input(Vec(fetchWidth, Bool())) // mask of branches from I$
 75     val f3_bpd_resp   = Valid(new BpdResp)
 76     val f3_btb_update = Flipped(Valid(new BoomBTBUpdate))
 77     val f3_ras_update = Flipped(Valid(new RasUpdate))
 78     val f3_stall      = Input(Bool()) // f4 is not ready -- back-pressure the f3 stage.
 79     val f3_will_redirect = Input(Bool())
 80
 81     // Fetch4
 82     val f4_redirect   = Input(Bool()) // I$ is being redirected from F4.
 83     val f4_taken      = Input(Bool()) // I$ is being redirected from F4 (and it is to take a CFI).
 84
 85     // Commit
 86     val bim_update    = Flipped(Valid(new BimUpdate))
 87     val bpd_update    = Flipped(Valid(new BpdUpdate))
 88
 89     // Other
 90     val br_unit_resp  = Input(new BranchUnitResp())
 91     val fe_clear      = Input(Bool()) // The FrontEnd needs to be cleared (due to redirect or flush).
 92     val ftq_restore   = Flipped(Valid(new RestoreHistory))
 93     val flush         = Input(Bool()) // pipeline flush from ROB TODO CODEREVIEW (redudant with fe_clear?)
 94     val redirect      = Input(Bool())
 95     val status_prv    = Input(UInt(freechips.rocketchip.rocket.PRV.SZ.W))
 96     val status_debug  = Input(Bool())
 97   })
 98
 99   //************************************************
100   // construct all of the modules
101
102   val btb = BoomBTB(boomParams, bankBytes)
103   val bpd = BoomBrPredictor(boomParams)
104
105   btb.io.status_debug := io.status_debug
106   bpd.io.status_prv := io.status_prv
107   bpd.io.do_reset := false.B // TODO
108
109   //************************************************
110   // Branch Prediction (F0 Stage)
111
112   btb.io.req := io.s0_req
113   bpd.io.req := io.s0_req
```

