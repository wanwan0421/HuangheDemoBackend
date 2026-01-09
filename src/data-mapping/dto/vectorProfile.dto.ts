export interface VectorProfile {
    geometry_type: 'Point' | 'Line' | 'Polygon'
    topology_valid: boolean
    attributes: {
        name: string
        type: 'Int' | 'Float' | 'String' | 'Boolean' | 'Date'
    }
}