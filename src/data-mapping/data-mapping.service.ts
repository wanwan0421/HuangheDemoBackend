import { Injectable, Logger } from '@nestjs/common';
import { DataSemanticProfile } from './dto/dataSemanticProfile.dto';
import * as fs from 'fs';
import * as path from 'path';

@Injectable()
export class DataMappingService {
  private readonly logger = new Logger(DataMappingService.name);

  /**
   * 分析上传的数据文件并生成语义画像
   * @param filePath 文件路径
   * @returns DataSemanticProfile
   */
  async analyzeUploadedData(filePath: string): Promise<DataSemanticProfile> {
    try {
      // 检查文件是否存在
      if (!fs.existsSync(filePath)) {
        throw new Error(`文件不存在: ${filePath}`);
      }

      const fileExtension = path.extname(filePath).toLowerCase();
      const fileName = path.basename(filePath);
      const fileStats = fs.statSync(filePath);

      // 基于文件扩展名判断数据类型
      const dataForm = this.inferDataForm(fileExtension);

      // 构建基础语义画像
      const profile: DataSemanticProfile = {
        id: this.generateDataId(fileName, fileStats.mtime),
        form: dataForm,
      };

      // 根据数据类型进行详细分析
      switch (dataForm) {
        case 'Raster':
          await this.analyzeRasterData(filePath, profile);
          break;
        case 'Vector':
          await this.analyzeVectorData(filePath, profile);
          break;
        case 'Table':
          await this.analyzeTableData(filePath, profile);
          break;
        case 'Timeseries':
          await this.analyzeTimeseriesData(filePath, profile);
          break;
        case 'Parameter':
          await this.analyzeParameterData(filePath, profile);
          break;
      }

      this.logger.log(`成功分析数据文件: ${fileName}, 类型: ${dataForm}`);
      return profile;
    } catch (error) {
      this.logger.error(`分析数据文件失败: ${error.message}`, error.stack);
      throw error;
    }
  }

  /**
   * 根据文件扩展名推断数据形式
   */
  private inferDataForm(extension: string): 'Raster' | 'Vector' | 'Table' | 'Timeseries' | 'Parameter' {
    const rasterExtensions = ['.tif', '.tiff', '.geotiff', '.img', '.hdf'];
    const vectorExtensions = ['.shp', '.geojson', '.json', '.kml', '.gml'];
    const tableExtensions = ['.csv', '.xlsx', '.xls', '.dbf'];
    const timeseriesExtensions = ['.nc', '.txt', '.dat'];

    if (rasterExtensions.includes(extension)) {
      return 'Raster';
    } else if (vectorExtensions.includes(extension)) {
      return 'Vector';
    } else if (tableExtensions.includes(extension)) {
      return 'Table';
    } else if (timeseriesExtensions.includes(extension)) {
      // 需要进一步分析内容来判断是否为时序数据
      return 'Timeseries';
    } else {
      return 'Parameter';
    }
  }

  /**
   * 生成数据ID
   */
  private generateDataId(fileName: string, modifiedTime: Date): string {
    const timestamp = modifiedTime.getTime();
    const nameHash = Buffer.from(fileName).toString('base64').substring(0, 8);
    return `data_${nameHash}_${timestamp}`;
  }

  /**
   * 分析栅格数据
   */
  private async analyzeRasterData(
    filePath: string,
    profile: DataSemanticProfile,
  ): Promise<void> {
    // TODO: 使用 GDAL 或其他库读取栅格元数据
    // 这里先设置基本结构，实际实现需要相应的库
    profile.raster = {
      // 以下字段需要从实际栅格文件中读取
      // bands: undefined,
      // resolution: undefined,
      // nodata_value: undefined,
      // color_interpretation: undefined,
    };

    // 空间信息（待实现）
    profile.spatial = {
      // crs: undefined,
      // extent: undefined,
    };

    // 语义描述（待LLM分析）
    profile.semantic = '栅格数据 - 需要进一步语义分析';
  }

  /**
   * 分析矢量数据
   */
  private async analyzeVectorData(
    filePath: string,
    profile: DataSemanticProfile,
  ): Promise<void> {
    // TODO: 使用 GDAL/OGR 或 geojson 库读取矢量数据
    const extension = path.extname(filePath).toLowerCase();

    if (extension === '.geojson' || extension === '.json') {
      try {
        const content = fs.readFileSync(filePath, 'utf-8');
        const geoJson = JSON.parse(content);

        profile.vector = {
          geometry_type: geoJson.features?.[0]?.geometry?.type || undefined,
          // fields: undefined, // 需要从 properties 中提取
          // feature_count: geoJson.features?.length,
        };

        // 尝试提取空间范围
        // profile.spatial = this.extractSpatialInfoFromGeoJSON(geoJson);
      } catch (error) {
        this.logger.warn(`解析GeoJSON文件失败: ${error.message}`);
      }
    }

    profile.vector = profile.vector || {};
    profile.semantic = '矢量数据 - 需要进一步语义分析';
  }

  /**
   * 分析表格数据
   */
  private async analyzeTableData(
    filePath: string,
    profile: DataSemanticProfile,
  ): Promise<void> {
    const extension = path.extname(filePath).toLowerCase();

    if (extension === '.csv') {
      try {
        const content = fs.readFileSync(filePath, 'utf-8');
        const lines = content.split('\n').filter((line) => line.trim());

        if (lines.length > 0) {
          const headers = lines[0].split(',').map((h) => h.trim());

          profile.table = {
            // columns: headers.map(name => ({ name, type: undefined })),
            // row_count: lines.length - 1,
          };

          // 检查是否包含时间字段
          const hasTimeColumn = headers.some((h) =>
            /time|date|datetime|timestamp/i.test(h),
          );
          profile.temporal = {
            has_time: hasTimeColumn,
          };
        }
      } catch (error) {
        this.logger.warn(`解析CSV文件失败: ${error.message}`);
      }
    }

    profile.table = profile.table || {};
    profile.semantic = '表格数据 - 需要进一步语义分析';
  }

  /**
   * 分析时序数据
   */
  private async analyzeTimeseriesData(
    filePath: string,
    profile: DataSemanticProfile,
  ): Promise<void> {
    // TODO: 分析时序数据结构
    profile.timeseries = {
      // time_column: undefined,
      // value_columns: undefined,
      // frequency: undefined,
    };

    profile.temporal = {
      has_time: true,
      // time_range: undefined, // 需要从数据中提取
    };

    profile.semantic = '时序数据 - 需要进一步语义分析';
  }

  /**
   * 分析参数数据
   */
  private async analyzeParameterData(
    filePath: string,
    profile: DataSemanticProfile,
  ): Promise<void> {
    // TODO: 解析参数文件
    profile.parameter = {
      // parameters: undefined,
    };

    profile.semantic = '参数数据 - 需要进一步语义分析';
  }

  /**
   * 批量分析多个文件
   */
  async analyzeMultipleFiles(
    filePaths: string[],
  ): Promise<DataSemanticProfile[]> {
    const results: DataSemanticProfile[] = [];

    for (const filePath of filePaths) {
      try {
        const profile = await this.analyzeUploadedData(filePath);
        results.push(profile);
      } catch (error) {
        this.logger.error(`分析文件 ${filePath} 失败: ${error.message}`);
        // 继续处理其他文件
      }
    }

    return results;
  }

  /**
   * 获取目录下所有数据文件并分析
   */
  async analyzeDirectory(dirPath: string): Promise<DataSemanticProfile[]> {
    if (!fs.existsSync(dirPath)) {
      throw new Error(`目录不存在: ${dirPath}`);
    }

    const files = this.getAllDataFiles(dirPath);
    return await this.analyzeMultipleFiles(files);
  }

  /**
   * 递归获取目录下所有数据文件
   */
  private getAllDataFiles(dirPath: string): string[] {
    const dataFiles: string[] = [];
    const supportedExtensions = [
      '.tif',
      '.tiff',
      '.shp',
      '.geojson',
      '.json',
      '.csv',
      '.xlsx',
      '.xls',
      '.nc',
      '.hdf',
      '.kml',
    ];

    const scanDirectory = (dir: string) => {
      const items = fs.readdirSync(dir);

      for (const item of items) {
        const fullPath = path.join(dir, item);
        const stat = fs.statSync(fullPath);

        if (stat.isDirectory()) {
          scanDirectory(fullPath);
        } else if (stat.isFile()) {
          const ext = path.extname(item).toLowerCase();
          if (supportedExtensions.includes(ext)) {
            dataFiles.push(fullPath);
          }
        }
      }
    };

    scanDirectory(dirPath);
    return dataFiles;
  }
}
