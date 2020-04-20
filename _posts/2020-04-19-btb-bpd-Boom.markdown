---
layout: post
titile: "How BTB and BPD works in Boom Architecture"
categories: risc-v, boom
---

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

**ifu/frontend.scala
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

