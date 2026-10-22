"""Static query pairs for company_document_finder.

The checklist is fixed, so the query pairs derived from it are fixed too. This used to be an LLM
call whose prompt embedded the whole checklist and then asked the model to echo it back, one
object per item, "do not merge or skip any" — deterministic input, non-deterministic output.

`document` is the join key the validator stage matches on, so it must stay byte-stable.
Add an item here when the compliance checklist changes.
"""

COMPANY_DOCUMENT_QUERIES: list[dict] = [
    {
        "document": "Certificate of Incorporation",
        "query": "Is submission of the Certificate of Incorporation mandatory for bid eligibility?",
        "keywords": ["Certificate of Incorporation", "COI", "proof of incorporation", "registration certificate under Companies Act", "incorporation certificate"],
    },
    {
        "document": "Partnership Deed",
        "query": "Does the tender require a registered Partnership Deed to be submitted?",
        "keywords": ["Partnership Deed", "registered partnership deed", "partnership firm registration", "deed of partnership", "Indian Partnership Act"],
    },
    {
        "document": "LLP Agreement",
        "query": "Does the tender require the LLP Agreement or LLP incorporation proof?",
        "keywords": ["LLP Agreement", "Limited Liability Partnership Agreement", "LLP incorporation certificate", "LLPIN", "Form 3 LLP"],
    },
    {
        "document": "MOA",
        "query": "Is the Memorandum of Association required as part of the bid documents?",
        "keywords": ["Memorandum of Association", "MOA", "MoA of the company", "memorandum and articles", "object clause"],
    },
    {
        "document": "AOA",
        "query": "Is the Articles of Association required as part of the bid documents?",
        "keywords": ["Articles of Association", "AOA", "AoA of the company", "memorandum and articles", "articles of the company"],
    },
    {
        "document": "Udyam/MSME Registration",
        "query": "Does the tender ask for Udyam or MSME registration for exemption or eligibility?",
        "keywords": ["Udyam Registration", "MSME Certificate", "Udyog Aadhaar", "Udyam Registration Number", "MSME registered bidder", "micro small medium enterprise"],
    },
    {
        "document": "Startup India Certificate",
        "query": "Does the tender grant relaxation to bidders holding a Startup India recognition certificate?",
        "keywords": ["Startup India Certificate", "DPIIT recognition", "startup recognition certificate", "DIPP certificate", "startup exemption"],
    },
    {
        "document": "Shop & Establishment Registration",
        "query": "Is a Shop and Establishment registration certificate required from the bidder?",
        "keywords": ["Shop and Establishment Registration", "Shops and Establishments Act", "Gumasta License", "shop establishment certificate", "S&E registration"],
    },
    {
        "document": "Trade License",
        "query": "Does the tender mandate submission of a valid Trade License?",
        "keywords": ["Trade License", "municipal trade license", "valid trade licence", "trade licence certificate", "corporation trade license"],
    },
    {
        "document": "Factory License",
        "query": "Is a Factory License under the Factories Act required for this tender?",
        "keywords": ["Factory License", "Factories Act licence", "factory registration certificate", "Form 4 factory licence", "factory licence copy"],
    },
    {
        "document": "IEC Certificate",
        "query": "Does the tender require an Importer Exporter Code certificate?",
        "keywords": ["IEC Certificate", "Importer Exporter Code", "IEC code", "DGFT IEC", "import export code certificate"],
    },
    {
        "document": "Import/Export License",
        "query": "Does the tender require any import or export licence for the supplied goods?",
        "keywords": ["import licence", "export licence", "DGFT licence", "import authorization", "export authorization"],
    },
    {
        "document": "PAN Card",
        "query": "Is a copy of the PAN card mandatory with the bid submission?",
        "keywords": ["PAN Card", "Permanent Account Number", "PAN copy", "PAN of the bidder", "income tax PAN"],
    },
    {
        "document": "TAN Certificate",
        "query": "Does the tender require the TAN allotment certificate?",
        "keywords": ["TAN Certificate", "Tax Deduction Account Number", "TAN allotment letter", "TDS TAN", "TAN number proof"],
    },
    {
        "document": "GST Registration Certificate",
        "query": "Is a valid GST registration certificate required for bid eligibility?",
        "keywords": ["GST Registration Certificate", "GSTIN", "GST registration copy", "Form GST REG-06", "goods and services tax registration"],
    },
    {
        "document": "GST Amendment Certificate",
        "query": "Does the tender ask for a GST amendment certificate reflecting changed particulars?",
        "keywords": ["GST Amendment Certificate", "amended GST registration", "GST REG-15", "amendment in GST registration", "revised GSTIN certificate"],
    },
    {
        "document": "GST LUT",
        "query": "Is a Letter of Undertaking under GST required for this tender?",
        "keywords": ["GST LUT", "Letter of Undertaking", "LUT under GST", "GST RFD-11", "export without payment of tax"],
    },
    {
        "document": "GST Composition Certificate",
        "query": "Does the tender require proof of GST composition scheme registration, if applicable?",
        "keywords": ["GST Composition Certificate", "composition scheme", "GST CMP-02", "composition dealer", "composition levy intimation"],
    },
    {
        "document": "Professional Tax Registration",
        "query": "Is Professional Tax registration required to be submitted with the bid?",
        "keywords": ["Professional Tax Registration", "PT registration certificate", "PTRC", "PTEC", "profession tax enrolment"],
    },
    {
        "document": "EPFO Registration",
        "query": "Does the tender require EPF registration proof for the bidder?",
        "keywords": ["EPFO Registration", "EPF registration certificate", "Provident Fund registration", "PF code number", "EPF establishment code"],
    },
    {
        "document": "ESIC Registration",
        "query": "Does the tender require ESIC registration proof for the bidder?",
        "keywords": ["ESIC Registration", "ESI registration certificate", "Employees State Insurance", "ESIC code number", "ESI establishment code"],
    },
    {
        "document": "Labour License",
        "query": "Is a Contract Labour licence required for executing this tender?",
        "keywords": ["Labour License", "Contract Labour Regulation and Abolition Act", "CLRA licence", "labour licence copy", "contractor labour licence"],
    },
    {
        "document": "NSIC Certificate",
        "query": "Does the tender allow exemption to bidders holding an NSIC registration certificate?",
        "keywords": ["NSIC Certificate", "NSIC registration", "National Small Industries Corporation", "single point registration scheme", "SPRS certificate"],
    },
    {
        "document": "DIC Registration",
        "query": "Does the tender ask for District Industries Centre registration?",
        "keywords": ["DIC Registration", "District Industries Centre", "DIC certificate", "SSI registration", "provisional registration certificate"],
    },
    {
        "document": "ISO Certificates",
        "query": "Does the tender require the bidder to hold ISO certification?",
        "keywords": ["ISO Certificate", "ISO 9001", "ISO 14001", "ISO 45001", "ISO certification mandatory", "quality certification"],
    },
    {
        "document": "Quality Management Certificates",
        "query": "Does the tender require any quality management system certification other than ISO?",
        "keywords": ["Quality Management System", "QMS certificate", "quality assurance certificate", "BIS certification", "NABL accreditation", "quality control certificate"],
    },
    {
        "document": "Other industry-specific registrations",
        "query": "Which additional licences, registrations or statutory certificates does the tender list under eligibility?",
        "keywords": ["statutory registration", "mandatory licence", "eligibility documents required", "registration certificate to be submitted", "documents to be uploaded", "requisite licence"],
    },
]
