// define the structure of the external portal API response for type security of ResourceService
// the item in the content array of external portal API response
export interface Md5Item {
    md5: string;
    name: string;
    viewCount: number;
}

// the data field structure of external portal API paging response
export interface PortalMd5Data {
    total: number;
    content: Md5Item[];
}

// the paging result structure of internal used service
export interface OnePageMd5Result {
    totalNumber: number;
    md5List: string[]; // only return the md5 list for internal use
}

export interface MdlEventParameter {
    datasetReference?: string;
}