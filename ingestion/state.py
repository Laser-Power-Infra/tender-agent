from typing import TypedDict

class IngestionState(TypedDict, total=False):

    job_id:str
    document_id:str
    file_url:str
    original_url:str
    reference_no:str
    document_tag:str
    document_name:str|None

    #local document
    working_dir:str
    file_path:str
    doc_cache:str|None


    #page tracking
    total_pages:int
    current_page:int
    parsed_pages:list[dict]

    # Current page processing
    page_markdown:str
    page_chunks:list[dict]

    # Processing
    status:str
    error:str|None    

