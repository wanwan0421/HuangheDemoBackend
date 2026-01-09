export interface RasterProfile {
    resolution: {
        x: number,
        y: number
    }
    unit: string
    value_range?: [number, number]
    nodata: number
    band_count: number
}