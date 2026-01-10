import { Injectable, Logger } from '@nestjs/common';
import { DataSemanticProfile, DatasetPackage } from './dto/dataSemanticProfile.dto';
import * as fs from 'fs';
import * as path from 'path';
import * as unzipper from 'unzipper';

@Injectable()
export class DataMappingService {
    private readonly logger = new Logger(DataMappingService.name);

    /**
     * 分析上传的数据文件并生成语义描述协议
     * @param filePath 文件路径
     * @returns DataSemanticProfile
     */
    async analyzeUploadedData(filePath: string): Promise<DataSemanticProfile> {
        try {
            const pkg = await this.buildDatasetPackage(filePath);
            // 判断数据类型
            const { form, primaryFile } = this.inferDataForm(pkg);

            // 构建基础语义画像
            const profile: DataSemanticProfile = {
                id: this.generateDataId(primaryFile || 'unknown'),
                format: path.extname(primaryFile || '').toLowerCase(),
                form: form,
            };

            // 根据数据类型进行详细分析
            switch (form) {
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

            this.logger.log(`成功分析数据文件: ${primaryFile}, 类型: ${form}`);
            return profile;
        } catch (error) {
            this.logger.error(`分析数据文件失败: ${error.message}`, error.stack);
            throw error;
        }
    }

    /**
     * 解压用户上传的数据包并返回文件列表
     * @param inputPath 上传的文件或目录路径
     * @return DatasetPackage
     */
    async buildDatasetPackage(inputPath: string): Promise<DatasetPackage> {
        // 检查文件是否存在
        if (!fs.existsSync(inputPath)) {
            throw new Error(`文件不存在: ${inputPath}`);
        }
        const fileExtension = path.extname(inputPath).toLowerCase();
        const fileStats = fs.statSync(inputPath);

        // 压缩包处理
        if (fileStats.isFile() && ['.zip', '.tar', '.gz', '.rar'].includes(fileExtension)) {
            const extractDir = inputPath.replace(path.extname(inputPath), '');
            await fs.createReadStream(inputPath).pipe(unzipper.Extract({ path: extractDir })).promise();

            return this.collectFiles(extractDir);
        }

        // 单文件处理
        if (fileStats.isFile()) {
            return {
                rootPath: path.dirname(inputPath),
                files: [inputPath],
                primaryFile: inputPath,
            }
        }

        // 目录处理（如果传入的是已经解压好的文件夹，直接扫描）
        return this.collectFiles(inputPath);
    }

    /**
     * 递归收集目录下所有文件
     * @param dirPath 目录路径
     * @return DatasetPackage
     */
    private collectFiles(dirPath: string): DatasetPackage {
        const files: string[] = [];

        const scanDirectory = (dir: string) => {
            for (const item of fs.readdirSync(dir)) {
                const fullPath = path.join(dir, item);
                const stat = fs.statSync(fullPath);
                if (stat.isDirectory()) {
                    scanDirectory(fullPath);
                } else {
                    files.push(fullPath);
                }
            }
        }

        scanDirectory(dirPath);
        return { rootPath: dirPath, files };
    }

    /**
     * 推断数据形式
     */
    private inferDataForm(pkg: DatasetPackage): {form: 'Raster' | 'Vector' | 'Table' | 'Timeseries' | 'Parameter' | 'Unknown'; primaryFile?: string} {
        const extensions = pkg.files.map(f => path.extname(f).toLowerCase());

        // Parameter 优先级最高
        if (extensions.includes('.xml')) {
            return {
                form: 'Parameter',
                primaryFile: pkg.files.find(f => f.endsWith('.xml'))
            };
        }

        // Vector: Shapefile
        if (['.shp', '.shx', '.dbf'].every(ext => extensions.includes(ext))) {
            return {
                form: 'Vector',
                primaryFile: pkg.files.find(f => f.endsWith('.shp'))
            };
        }

        // Vector: 单文件
        const vectorExtensions = ['.geojson', '.json', '.kml', '.gml'];
        const vector = pkg.files.find(f => vectorExtensions.includes(path.extname(f).toLowerCase()));
        if (vector) {
            return {
                form: 'Vector',
                primaryFile: vector
            };
        }

        // Raster
        const rasterExtensions = ['.tif', '.tiff', '.geotiff', '.img', '.hdf', '.asc', 'vrt'];
        const raster = pkg.files.find(f => rasterExtensions.includes(path.extname(f).toLowerCase()));
        if (raster) {
            return {
                form: 'Raster',
                primaryFile: raster
            };
        }
            
        // Table
        const tableExtensions = ['.csv', '.xlsx', '.xls'];
        const table = pkg.files.find(f => tableExtensions.includes(path.extname(f).toLowerCase()));
        if (table) {
            return {
                form: 'Table',
                primaryFile: table
            };
        }

        // Timeseries
        const timeseriesExtensions = ['.nc', '.txt', '.dat'];
        const timeseries = pkg.files.find(f => timeseriesExtensions.includes(path.extname(f).toLowerCase()));
        if (timeseries) {
            return {
                form: 'Timeseries',
                primaryFile: timeseries
            };
        }

        return {
            form: 'Unknown',
            primaryFile: ''
        };
    }

    /**
     * 生成数据ID
     */
    private generateDataId(seed: string) {
        return `data_${Date.now()}_${seed}`;
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
