export interface VectorProfile {
    geometry_type: 'Point' | 'Line' | 'Polygon';
    topology_valid: boolean;
    attributes: Array<{
        name: string;
        type: 'Int' | 'Float' | 'String' | 'Boolean' | 'Date';
    }>;
}