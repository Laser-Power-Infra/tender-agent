const abdc = {
  tender_id: "GEM/2026/B/8000059",
  sections: {
    reverse_auction: {
      applicable: False,
      clauses: [],
      summary: "No relevant context found",
      evidence: { output: "", found_document: "", documentId: "", pageNo: 0 },
    },
    basic_details: {
      title: "",
      reference_no: "",
      organization: "",
      eligibility: [],
      important_dates: [],
      summary:
        "Purchaser may change quantity up to ±25%; additional delivery time = (increased/original) × original delivery period, and may be extended up to the original delivery period.",
      evidence: {
        output:
          "Option allows ±25% quantity change; extra delivery time equals (increased/original)×original delivery period, extendable up to the original period.",
        found_document: "GEM-2026-B-8000059_20260911_054929.pdf",
        documentId: "",
        pageNo: 7,
      },
    },
    emd_agent: {
      emdAmount: "",
      emdPaymentMode: "",
      emdExemption: [],
      emdValidity: "",
      summary: "No relevant context found",
      evidence: { output: "", found_document: "", documentId: "", pageNo: 0 },
    },
    gem_document_agent: {
      documents: [
        "Registration with Competent Authority (for bidders from countries sharing a land border with India)",
        "Buyer uploaded Additional Terms and Conditions (ATC) document",
        "EMD (Earnest Money Deposit)",
        "Signed Integrity Pact",
      ],
      summary:
        "Required bid documents shown in provided results: Competent Authority registration (if land-border country), buyer-uploaded ATC file, EMD, and signed Integrity Pact (EMD and pact may be submitted within 5 days).",
      evidence: {
        output:
          "Bidders from countries sharing a land border must be registered with the Competent Authority to be eligible to bid.",
        found_document: "GEM-2026-B-8000059_20260911_054929.pdf",
        documentId: "GEM-2026-B-8000059_20260911_054929.pdf",
        pageNo: 8,
      },
    },
    common_document_agent: {
      documents: ["Make in India Declaration", "Bid Security Declaration"],
      summary:
        "Make in India and Bid Security Declarations are required — bidders from countries sharing a land border must be registered with the Competent Authority and must undertake compliance; false declaration may cause termination.",
      evidence: {
        output:
          "Bidders from countries sharing a land border must be registered with Competent Authority and undertake compliance; false declaration leads to termination.",
        found_document: "GEM-2026-B-8000059_20260911_054929.pdf",
        documentId: "GEM-2026-B-8000059_20260911_054929.pdf",
        pageNo: 8,
      },
    },
  },
  failed: [],
  degraded: [],
};
