const abcd = (final = {
  tender_id: "2026_HBC_546595_1",
  sections: {
    reverse_auction: {
      applicable: False,
      clauses: [],
      summary: "No relevant context found",
      evidence: { output: "", found_document: "", documentId: "", pageNo: 0 },
    },
    basic_details: {
      organization: "",
      date_of_submission: "",
      tender_fees: "Rs. 5,000 plus GST at 18% or applicable, payable online.",
      document_fees: "",
      delivery_location: "",
      delivery_period:
        "Time and date of delivery are stipulated in Annexure B to Schedule D of the contract or purchase order.",
      inspection_required: "",
      portal_payment_required:
        "Tender document fee must be paid online through the e-procurement portal; EMD may be paid through RTGS/NEFT or offline bank guarantee.",
      bid_validity_days:
        "120 days from technical bid opening or 90 days from price bid opening, whichever is later.",
      exemptions: ["Tender Fee exemption", "EMD exemption"],
      forms_annexures: [
        "Prescribed tender form",
        "Signed terms and conditions of contract",
        "Annexure A",
        "Annexure B",
        "Technical offer documents",
        "Qualifying requirements",
        "Technical specifications",
        "Schedule of deliveries",
      ],
      summary:
        "Tender document fee is Rs. 5,000 plus applicable GST, payable online. Bids remain valid for the later of 120 technical-bid days or 90 price-bid days.",
      evidence: {
        output:
          "Tender fee, online payment method, bid validity, and required annexures are specified.",
        found_document: "Tender-Document-XLPE.pdf",
        documentId: "",
        pageNo: 5,
      },
    },
    emd_agent: {
      emdAmount: "Rs. 41,00,000/-",
      emdPaymentMode: "RTGS/NEFT or offline payment via Bank Guarantee",
      emdExemption: [],
      emdValidity: "",
      summary:
        "EMD of Rs. 41,00,000/- is payable through RTGS/NEFT or offline Bank Guarantee; no EMD exemption or validity is stated.",
      evidence: {
        output:
          "EMD requires Rs. 41,00,000/- through RTGS/NEFT or offline Bank Guarantee.",
        found_document: "Tender-Document-XLPE.pdf",
        documentId: "",
        pageNo: 5,
      },
    },
    non_gem_document_agent: {
      documents: [
        "Prescribed Tender Form",
        "Signed Terms and Conditions of Contract",
        "Tender Annexure A",
        "Tender Annexure B",
        "Technical Bid",
        "Priced BOQ",
        "EMD Bank Guarantee or approved EMD payment proof",
        "Tender Fee Online Payment Proof",
      ],
      summary:
        "The tender requires the prescribed and signed tender forms, annexures, technical offer, completed price schedule, tender fee proof, and EMD documentation.",
      evidence: {
        output:
          "Bidders must submit signed tender forms, contract terms, Annexures A and B, technical offer, and completed online payments.",
        found_document: "Tender-Document-XLPE.pdf",
        documentId: "2026_HBC_546595_1",
        pageNo: 7,
      },
    },
    common_document_agent: {
      documents: [
        "Priced BOQ",
        "Price Schedule",
        "Financial Bid",
        "Bank Guarantee for EMD",
        "Performance Bank Guarantee",
      ],
      summary:
        "The tender explicitly requires submission of the completed BOQ and bid materials; EMD and performance guarantees are required in the stated circumstances.",
      evidence: {
        output:
          "Completed BOQ must be uploaded after entering bidder details and values; modification or replacement may cause rejection.",
        found_document: "BOQ_626241.xls",
        documentId: "2026_HBC_546595_1",
        pageNo: 1,
      },
    },
  },
  failed: [],
  degraded: [],
});
