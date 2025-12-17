import { thirdIndexModel } from "./thirdIndexModel.interface"

export interface thirdIndex {
    code: string,
    name_en: string,
    name_cn: string,
    field_name: string,
    models: thirdIndexModel[],
}