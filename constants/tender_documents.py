TENDER_DOCUMENTS = {

    # ============================================================
    # 1. GEМ-ONLY
    # Documents / sections primarily specific to GeM participation
    # ============================================================

    "gem_only": {

        "gem_registration": [
            "GeM Seller Registration",
            "GeM Seller ID",
            "GeM Organization Profile",
            "GeM Seller Profile",
            "GeM Primary User Details",
            "GeM Authorized Person Details",
            "GeM Seller Account Details",
            "GeM Bank Account Registration",
            "GeM ITR Verification Details"
        ],

        "gem_catalogue_listing": [
            "GeM Product Catalogue",
            "GeM Product Listing",
            "GeM Product Category Mapping",
            "GeM Product Specification Mapping",
            "GeM Product Attributes",
            "GeM Product Images",
            "GeM Product Datasheet",
            "GeM Product Brand Details",
            "GeM Product Model Details",
            "GeM Product HSN Details",
            "GeM Product Country of Origin Details",
            "GeM Product Warranty Details",
            "GeM Product OEM Details"
        ],

        "gem_service_listing": [
            "GeM Service Catalogue",
            "GeM Service Listing",
            "GeM Service Category Mapping",
            "GeM Service Attributes",
            "GeM Service Scope",
            "GeM Service SLA Details",
            "GeM Service Manpower Details",
            "GeM Service Pricing Details"
        ],

        "gem_bid_specific": [
            "GeM Bid Participation",
            "GeM Bid Response",
            "GeM Bid-specific Compliance",
            "GeM Bid-specific Documents",
            "GeM Bid-specific Undertakings",
            "GeM Bid-specific Declarations",
            "GeM Reverse Auction Participation",
            "GeM Bid/RA Eligibility Documents",
            "GeM Seller Undertaking",
            "GeM Bid Acceptance"
        ],

        "gem_order_and_contract": [
            "GeM Purchase Order",
            "GeM Contract",
            "GeM Order Acceptance",
            "GeM Contract Acceptance",
            "GeM Delivery Details",
            "GeM Consignee Details",
            "GeM Invoice Submission",
            "GeM CRAC-related Documents",
            "GeM Payment-related Documents"
        ]
    },


    # ============================================================
    # 2. NON-GEM ONLY
    # Primarily associated with CPPP / State eProcurement /
    # Department-specific tenders and offline tender requirements
    # ============================================================

    "non_gem_only": {
    "tender_notice_documents": [
      "Notice Inviting Tender (NIT)",
      "Request for Proposal (RFP)",
      "Request for Quotation (RFQ)",
      "Tender Document",
      "Bid Document",
      "Tender Schedule",
      "Tender Specifications",
      "Special Conditions of Contract",
      "General Conditions of Contract",
      "Instructions to Bidders",
      "Corrigendum",
      "Pre-bid Clarification",
      "Pre-bid Meeting Documents"
    ],

    "non_gem_portal_registration": [
      "CPPP/eProcure Registration",
      "State eProcurement Portal Registration",
      "Department-specific Portal Registration",
      "Portal Bidder Enrollment",
      "Portal DSC Registration",
      "Portal Vendor Registration"
    ],

    "tender_fee": [
      "Tender Fee Payment Receipt",
      "Tender Fee Demand Draft",
      "Tender Fee Banker's Cheque",
      "Tender Fee Online Payment Proof",
      "Tender Fee Exemption Certificate",
      "Tender Fee Exemption Declaration"
    ],

    "offline_emd_formats": [
      "EMD Demand Draft",
      "EMD Bank Guarantee",
      "EMD Fixed Deposit Receipt",
      "EMD Banker's Cheque",
      "EMD Treasury Challan",
      "Physical EMD Submission Proof",
      "EMD Original Instrument",
      "EMD Exemption Certificate"
    ],

    "non_gem_bid_submission": [
      "Technical Bid Cover",
      "Financial Bid Cover",
      "Pre-Qualification Bid",
      "Technical Bid",
      "Commercial Bid",
      "Financial Bid",
      "Unpriced BOQ",
      "Priced BOQ",
      "Physical Bid Documents",
      "Hard Copy Submission",
      "Original Document Submission",
      "Bid Submission Receipt"
    ],

    "tender_specific_annexures": [
      "Tender Annexure A",
      "Tender Annexure B",
      "Tender Annexure C",
      "Tender Annexure D",
      "Tender Annexure E",
      "Technical Format",
      "Financial Format",
      "Eligibility Form",
      "Experience Form",
      "Turnover Form",
      "Manufacturer Form",
      "Local Content Form",
      "Bidder Information Form",
      "Company Information Form",
      "Tender Checklist",
      "Price Schedule",
      "Department-specific Forms"
    ]
  },


    # ============================================================
    # 3. COMMON
    # Can be required in BOTH GeM and Non-GeM tenders
    # ============================================================

   "common": {
    "company_registration": [
      "Certificate of Incorporation",
      "Company PAN Card",
      "GST Registration Certificate",
      "Udyam Registration Certificate",
      "Memorandum of Association (MOA)",
      "PAN Card",
      "Trade Licence",
      "Factory Licence"
    ],

    "authorization": [
      "Authorization Letter",
      "Power of Attorney",
      "Board Resolution for Authorized Signatory",
      "PAN Card of Power of Attorney Holder"
    ],

    "tax_compliance": [
      "Income Tax Return",
      "GST Returns",
      "GSTR-3B Returns",
      "Professional Tax Registration Certificate",
      "Latest Professional Tax Challan",
      "ESI Registration Certificate",
      "Latest ESI Challan",
      "PF Registration Certificate",
      "Latest PF Challan"
    ],

    "financial": [
      "Audited Financial Statements",
      "CA Certified Turnover Certificate",
      "Net Worth Certificate",
      "Bank Solvency Certificate",
      "Annual Turnover Certificate",
      "Balance Sheet",
      "Profit and Loss Statement"
    ],

    "banking": [
      "Cancelled Cheque",
      "Bank Account Proof",
      "Bank Mandate"
    ],

    "experience": [
      "Purchase Order",
      "Supply Order",
      "Performance Certificate",
      "Experience Certificate"
    ],

    "quality_and_product": [
      "BIS Licence",
      "ISI Mark Licence",
      "ISO 9001 Certificate",
      "Type Test Certificate",
      "Routine Test Certificate",
      "Product Test Report",
      "Technical Datasheet",
      "Product Catalogue",
      "ISO Certificate",
      "BIS Certificate",
      "Quality Assurance Plan"
    ],

    "oem_authorization": [
      "OEM Authorization Certificate",
      "Manufacturer Authorization Letter",
      "Dealership Certificate",
      "Distributor Certificate"
    ],

    "local_content": [
      "Country of Origin Declaration",
      "Make in India Declaration",
      "Local Content Declaration"
    ],

    "msme_startup": [
      "MSME/Udyam Certificate",
      "DPIIT Startup Recognition Certificate"
    ],

    "bid_security": [
      "EMD Payment Receipt",
      "Bank Guarantee for EMD",
      "EMD Exemption Certificate",
      "Bid Security Declaration"
    ],

    "technical_bid": [
      "Technical Compliance Sheet",
      "Compliance Matrix",
      "Technical Datasheet",
      "Deviation Statement"
    ],

    "financial_bid": [
      "Priced BOQ",
      "Price Schedule",
      "Financial Bid"
    ],

    "undertakings": [
      "Tender Acceptance Undertaking",
      "No Deviation Undertaking",
      "Warranty Undertaking",
      "Delivery Commitment",
      "Non-Blacklisting Declaration",
      "Conflict of Interest Declaration"
    ],

    "post_award": [
      "Performance Bank Guarantee",
      "Contract Agreement",
      "Insurance Documents"
    ],

    "delivery": [
      "Delivery Challan",
      "Tax Invoice",
      "E-Way Bill",
      "Inspection Report",
      "Test Certificate",
      "Warranty Certificate"
    ],

    "import_export": [
      "Import Export Code (IEC)",
      "Country of Origin Certificate",
      "Bill of Entry"
    ],

    "product_technical": [
      "Guaranteed Technical Particulars (GTP)"
    ],

    "manufacturing_capability": [
      "Annual Manufacturing Capacity",
      "Factory Layout Plan",
      "List of Machinery",
      "List of Testing Equipment",
      "List of Manpower"
    ]
  }
}