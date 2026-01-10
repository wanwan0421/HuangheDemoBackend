import { RasterProfile } from './rasterProfile.dto';
import { VectorProfile } from './vectorProfile.dto';
import { TableProfile } from './tableProfile.dto';
import { TimeseriesProfile } from './timeseriesProfile.dto';
import { ParameterProfile } from './parameterProfile.dto';

export interface DataSemanticProfile {
  // 第一层：最小通用语义内核
  id: string
  format: string
  form: 'Raster' | 'Vector' | 'Table' | 'Timeseries' | 'Parameter' | 'Unknown'
  spatial?: {
    crs?: string
    extent?: [number, number, number, number]
  }
  temporal?: {
    has_time: boolean
    time_range?: [string, string]
  }
  semantic?: string

  // 第二层：类型化语义描述
  raster?: RasterProfile
  vector?: VectorProfile
  table?: TableProfile
  timeseries?: TimeseriesProfile
  parameter?: ParameterProfile

  // 第三层：领域语义扩展
  domain?: string
}

export interface DatasetPackage {
    rootPath: string;
    files: string[];
    primaryFile?: string;
}