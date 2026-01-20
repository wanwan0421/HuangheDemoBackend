import { Injectable, Logger } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { Model, Types } from 'mongoose';
import { Observable } from 'rxjs';
import { DataFormCandidate, DataSemanticProfile, DatasetPackage } from './dto/dataSemanticProfile.dto';
import { Session, SessionDocument } from '../chat/schemas/session.schema';
import { Message, MessageDocument } from '../chat/schemas/message.schema';
import * as fs from 'fs';
import * as path from 'path';
import * as unzipper from 'unzipper';
import { spawn } from 'child_process';
import axios from 'axios';
import type { Response } from 'express';

@Injectable()
export class DataMappingService {
    private readonly logger = new Logger(DataMappingService.name);
    private readonly pythonInspectorScript = path.join(__dirname, 'data-inspector.py');
    private readonly pythonExe = path.join(__dirname, '..', '..', '..', 'venv', 'Scripts', 'python.exe');

    constructor(
        @InjectModel(Session.name) private readonly sessionModel: Model<SessionDocument>,
        @InjectModel(Message.name) private readonly messageModel: Model<MessageDocument>,
    ) {}

    /**
     * 生成数据ID
     */
    private generateDataId(seed: string) {
        return `data_${Date.now()}_${seed}`;
    }

    /**
     * 分析上传的数据文件并生成语义描述协议
     * @param filePath 文件路径
     * @returns DataSemanticProfile
     */
    async analyzeUploadedData(filePath: string): Promise<DataSemanticProfile> {
        try {
            const pkg = await this.buildDatasetPackage(filePath);
            // 判断数据类型（第一阶段扩展名推断 + 第二阶段内容细化 + 第三阶段LLM辅助）
            
            // 第一阶段：基于扩展名推断
            const { candidates, primaryFile } = this.inferDataFormByExtension(pkg);
            
            // 第二阶段：基于内容细化判断（使用Python inspector）
            if (!primaryFile) {
                throw new Error('无法确定主要数据文件');
            }
            const refinedCandidates = await this.refineDataFormByContent(primaryFile, candidates);
            const initialFormResult = this.confirmDataForm(refinedCandidates);
            
            // 构建基础语义画像
            const profile: DataSemanticProfile = {
                id: this.generateDataId(primaryFile || 'Unknown'),
                format: path.extname(primaryFile || '').toLowerCase(),
                form: initialFormResult.form,
            };

            // 第三阶段：深度元数据提取（使用Python inspector extract）
            await this.executeDetailedAnalysis(initialFormResult.form, primaryFile || filePath, profile);

            // 第四阶段：LLM 语义精炼与补全
            const finalProfile = await this.refineProfileWithLLM(profile, primaryFile || filePath);

            this.logger.log(`成功分析数据: ${profile.id}, 最终类型: ${finalProfile.form}`);
            return finalProfile;
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
     * 第一阶段：基于扩展名推断数据形式
     * @param pkg 数据包信息
     * @return 候选数据形式列表及主要文件
     */
    private inferDataFormByExtension(pkg: DatasetPackage): {candidates: DataFormCandidate[]; primaryFile?: string;} {
        const candidates: DataFormCandidate[] = [];
        const extensions = pkg.files.map(f => path.extname(f).toLowerCase());

        // Parameter (XML 文件 - 最高优先级)
        const xmlFile = pkg.files.find(f => f.endsWith('.xml'));
        if (xmlFile) {
            candidates.push({
                form: 'Parameter',
                primaryFile: xmlFile,
                confidence: 0.95
            });
            return { candidates, primaryFile: xmlFile };
        }

        // Vector: Shapefile (多文件组合)
        if (['.shp', '.shx', '.dbf'].every(ext => extensions.includes(ext))) {
            candidates.push({
                form: 'Vector',
                primaryFile: pkg.files.find(f => f.endsWith('.shp')) || '',
                confidence: 0.95
            });
            return { candidates, primaryFile: pkg.files.find(f => f.endsWith('.shp')) };
        }

        // Vector: KML, GML
        const kmlGmlFile = pkg.files.find(f => {
            const ext = path.extname(f).toLowerCase();
            return ['.kml', '.gml'].includes(ext);
        });
        if (kmlGmlFile) {
            candidates.push({
                form: 'Vector',
                primaryFile: kmlGmlFile,
                confidence: 0.9
            });
            return { candidates, primaryFile: kmlGmlFile };
        }

        // GeoJSON (可能是Vector，需要第二阶段确认)
        const geojsonFile = pkg.files.find(f => f.endsWith('.geojson'));
        if (geojsonFile) {
            candidates.push({
                form: 'Vector',
                primaryFile: geojsonFile,
                confidence: 0.9
            });
            return { candidates, primaryFile: geojsonFile };
        }

        // 歧义文件：.json可能是Vector或Table
        const jsonFile = pkg.files.find(f => f.endsWith('.json'));
        if (jsonFile) {
            candidates.push(
                { form: 'Vector', primaryFile: jsonFile, confidence: 0.5 },
                { form: 'Table', primaryFile: jsonFile, confidence: 0.3 }
            );
            return { candidates, primaryFile: jsonFile };
        }

        // 明确的Raster文件
        const rasterExtensions = ['.tif', '.tiff', '.geotiff', '.img', '.asc', '.vrt'];
        const rasterFile = pkg.files.find(f => rasterExtensions.includes(path.extname(f).toLowerCase()));
        if (rasterFile) {
            candidates.push({
                form: 'Raster',
                primaryFile: rasterFile,
                confidence: 0.9
            });
            return { candidates, primaryFile: rasterFile };
        }

        // 歧义文件：.hdf可能是 Raster或Timeseries
        const hdfFile = pkg.files.find(f => f.endsWith('.hdf'));
        if (hdfFile) {
            candidates.push(
                { form: 'Raster', primaryFile: hdfFile, confidence: 0.5 },
                { form: 'Timeseries', primaryFile: hdfFile, confidence: 0.5 }
            );
            return { candidates, primaryFile: hdfFile };
        }

        // 表格数据
        const tableExtensions = ['.csv', '.xlsx', '.xls'];
        const tableFile = pkg.files.find(f => tableExtensions.includes(path.extname(f).toLowerCase()));
        if (tableFile) {
            candidates.push({
                form: 'Table',
                primaryFile: tableFile,
                confidence: 0.85
            });
            // CSV可能包含地理坐标，需要第二阶段确认
            if (tableFile.endsWith('.csv')) {
                candidates.push({
                    form: 'Vector',
                    primaryFile: tableFile,
                    confidence: 0.3
                });
            }
            return { candidates, primaryFile: tableFile };
        }

        // 歧义文件：.nc可能是Timeseries或Raster
        const ncFile = pkg.files.find(f => f.endsWith('.nc'));
        if (ncFile) {
            candidates.push(
                { form: 'Timeseries', primaryFile: ncFile, confidence: 0.55 },
                { form: 'Raster', primaryFile: ncFile, confidence: 0.55 }
            );
            return { candidates, primaryFile: ncFile };
        }

        // 其他时序格式
        const timeseriesExtensions = ['.txt', '.dat'];
        const timeseriesFile = pkg.files.find(f => timeseriesExtensions.includes(path.extname(f).toLowerCase()));
        if (timeseriesFile) {
            candidates.push({
                form: 'Timeseries',
                primaryFile: timeseriesFile,
                confidence: 0.7
            });
            return { candidates, primaryFile: timeseriesFile };
        }

        return { candidates: [{ form: 'Unknown', primaryFile: '', confidence: 0 }] };
    }

    /**
     * 第二阶段：基于文件内容细化判断，根据内容特征提高置信度或改变分类
     * @param filePath 主要文件路径
     * @param candidates 第一阶段候选结果
     * @return 细化后的候选结果
     */
    private async refineDataFormByContent(filePath: string, candidates: DataFormCandidate[]): Promise<DataFormCandidate[]> {
        try {
            const inspectorResult = await this.executePythonInspector('detect', filePath);

            // 根据Python驱动的输出调整置信度
            if (!inspectorResult?.detected_form) {
                return candidates;
            }

            return candidates.map(candidate => {
                if (candidate.form === inspectorResult.detected_form) {
                    return {
                        ...candidate,
                        confidence: Math.max(candidate.confidence, inspectorResult.confidence)
                    };
                }

                return {
                    ...candidate,
                    confidence: Math.min(candidate.confidence, 0.2)
                }
            })
        } catch (error) {
            this.logger.warn(`第二阶段内容分析失败: ${error.message}`);
            return candidates;
        }
    }

    /**
     * 执行Python驱动脚本
     * @param jsonPath 输入JSON文件路径
     * @returns 脚本执行结果
    */
    private async executePythonInspector(command: string, filePath: string, extraArgs: string[] = []): Promise<any> {
        return new Promise((resolve, reject) => {
            // 运行python：ogms_driver.py
            const python = spawn(this.pythonExe, [this.pythonInspectorScript, command, filePath, ...extraArgs]);

            let stdoutData = '';
            let stderrData = '';

            python.stdout.on('data', (data) => {
                stdoutData += data.toString();
            });

            python.stderr.on('data', (data) => {
                stderrData += data.toString();
                this.logger.debug(`[Python Log]: ${data.toString().trim()}`);
            });

            python.on('close', (code) => {
                if (code !== 0) {
                    reject(new Error(`Python驱动脚本执行失败，退出码: ${code}, 错误: ${stderrData}`));
                } else {
                    try {
                        const lines = stdoutData.trim().split('\n');
                        const lastLine = lines[lines.length - 1];
                        const result = JSON.parse(lastLine);
                        resolve(result);
                    } catch (error) {
                        this.logger.error(`解析Python输出时出错: ${error.message}`);
                        resolve({ rawOutput: stdoutData });
                    }
                }
            });

            python.on('error', (error) => {
                reject(new Error(`执行Python驱动脚本时出错: ${error.message}`));
            })
        })
    }

    /**
     * 合并两个阶段的结果，选出最可能的数据类型
     */
    private confirmDataForm(candidates: DataFormCandidate[]): DataFormCandidate {
        if (candidates.length === 0) {
            return { form: 'Unknown', primaryFile: '', confidence: 0 };
        }

        // 按置信度排序
        const sorted = [...candidates].sort((a, b) => b.confidence - a.confidence);
        const topCandidate = sorted[0];

        // 如果置信度足够高，直接返回
        if (topCandidate.confidence >= 0.8) {
            return {
                form: topCandidate.form as 'Raster' | 'Vector' | 'Table' | 'Timeseries' | 'Parameter' | 'Unknown',
                primaryFile: topCandidate.primaryFile,
                confidence: topCandidate.confidence
            };
        }

        // 如果多个候选置信度接近，需要更多启发式规则
        const topConfidence = topCandidate.confidence;
        const similarCandidates = sorted.filter(c => Math.abs(c.confidence - topConfidence) < 0.1);

        if (similarCandidates.length > 1) {
            this.logger.warn(`多个类型候选置信度接近: ${similarCandidates.map(c => `${c.form}(${c.confidence})`).join(', ')}`);
        }

        return {
            form: topCandidate.form as 'Raster' | 'Vector' | 'Table' | 'Timeseries' | 'Parameter' | 'Unknown',
            primaryFile: topCandidate.primaryFile,
            confidence: topCandidate.confidence
        };
    }

    /**
     * 统一执行详细分析的封装
     */
    private async executeDetailedAnalysis(form: string, filePath: string, profile: DataSemanticProfile) {
        switch (form) {
            case 'Raster': await this.analyzeRasterData(filePath, profile); break;
            case 'Vector': await this.analyzeVectorData(filePath, profile); break;
            case 'Table': await this.analyzeTableData(filePath, profile); break;
            case 'Timeseries': await this.analyzeTimeseriesData(filePath, profile); break;
            case 'Parameter': await this.analyzeParameterData(filePath, profile); break;
        }
    }

    /**
     * 分析栅格数据
     * @param filePath 文件路径
     * @param profile 语义画像对象
     */
    private async analyzeRasterData(filePath: string, profile: DataSemanticProfile): Promise<void> {
        // 调用Python脚本获取栅格详细信息
        const inspectorResult = await this.executePythonInspector('extract', filePath, ['Raster']);

        // 映射结果到DataSemanticProfile
        if (!inspectorResult.error) {
            profile.spatial = inspectorResult.spatial;
            profile.raster = {
                resolution: inspectorResult.resolution,
                unit: inspectorResult.unit,
                value_range: inspectorResult.value_range,
                nodata: inspectorResult.nodata,
                band_count: inspectorResult.band_count
            };
        }
    }

    /**
     * 分析矢量数据
     * @param filePath 文件路径
     * @param profile 语义画像对象
     */
    private async analyzeVectorData(filePath: string, profile: DataSemanticProfile): Promise<void> {
        // 调用Python脚本获取矢量详细信息
        const inspectorResult = await this.executePythonInspector('extract', filePath, ['Vector']);

        // 映射结果到DataSemanticProfile
        if (!inspectorResult.error) {
            profile.spatial = inspectorResult.spatial;
            profile.vector = {
                geometry_type: inspectorResult.geometry_type,
                topology_valid: inspectorResult.topology_valid,
                attributes: inspectorResult.attributes
            };
        }
    }

    /**
     * 分析表格数据
     * @param filePath 文件路径
     * @param profile 语义画像对象
     */
    private async analyzeTableData(filePath: string, profile: DataSemanticProfile): Promise<void> {
        // 调用Python脚本获取表格详细信息
        const inspectorResult = await this.executePythonInspector('extract', filePath, ['Table']);

        // 映射结果到DataSemanticProfile
        if (!inspectorResult.error) {
            profile.table = {
                primary_key: inspectorResult.primary_key,
                time_field: inspectorResult.time_field
            };
        }
    }

    /**
     * 分析时序数据
     * @param filePath 文件路径
     * @param profile 语义画像对象
     */
    private async analyzeTimeseriesData(filePath: string, profile: DataSemanticProfile): Promise<void> {
        // 调用Python脚本获取时序详细信息
        const inspectorResult = await this.executePythonInspector('extract', filePath, ['Timeseries']);

        // 映射结果到DataSemanticProfile
        if (!inspectorResult.error) {
            profile.timeseries = {
                time_step: inspectorResult.time_step,
                aggregation: inspectorResult.aggregation,
            };
        }
    }

    /**
     * 分析参数数据
     * @param filePath 文件路径
     * @param profile 语义画像对象
     */
    private async analyzeParameterData(filePath: string, profile: DataSemanticProfile): Promise<void> {
        try {
            const content = fs.readFileSync(filePath, 'utf-8');
            const xdoMatch =
                content.match(/<XDO\s+([^\/>]+?)\s*\/>/i);

            if (!xdoMatch) {
                throw new Error('未找到 XDO 节点');
            }
            const attrText = xdoMatch[1];
            const attrRegex = /(\w+)\s*=\s*"([^"]*)"/g;
            const attrs: Record<string, string> = {};

            let attrMatch;
            while ((attrMatch = attrRegex.exec(attrText)) !== null) {
                attrs[attrMatch[1]] = attrMatch[2];
            }

            // kernelType → value_type
            const valueType = this.normalizeKernelType(attrs.kernelType);

            profile.parameter = {
                value_type: valueType,
                unit: attrs.unit, // 如果 XML 中没有 unit，这里就是 undefined
            };

            profile.semantic = '模型参数定义（Parameter），用于模型运行配置';
        } catch (error) {
            this.logger.warn(`解析参数文件失败: ${error.message}`);
            profile.parameter = undefined;
            profile.semantic = '参数数据（解析失败）';
        }
    }

    /**
     * 管道传输 Agent 数据扫描 SSE 流（推荐用于实时展示）
     * 直接将 Python Agent 的 SSE 流转发给前端，无需中间处理
     * @param filePath 待分析的文件路径
     * @param res Response 对象
     * @param sessionId 可选的会话ID
     */
    async pipeAgentDataScanSSE(filePath: string, res: any, sessionId?: string): Promise<void> {
        const agentApiUrl = `${process.env.agentUrl}/data-scan/stream`;
        try {
            const params = new URLSearchParams();
            params.append('file_path', filePath);
            if (sessionId) {
                params.append('session_id', sessionId);
            }

            const pythonRes = await axios({
                method: 'GET',
                url: `${agentApiUrl}?${params.toString()}`,
                responseType: 'stream',
                headers: {
                    Accept: 'text/event-stream',
                }
            });

            // 管道传输数据到客户端
            pythonRes.data.on('data', (chunk: Buffer) => {
                res.write(chunk);
            });

            pythonRes.data.on('end', () => {
                res.end();
            });

            pythonRes.data.on('error', (err: any) => {
                res.write(
                    `data: ${JSON.stringify({
                        type: 'error',
                        message: `Agent 流传输失败: ${err.message}`,
                    })}\n\n`,
                );
                res.end();
            });

            // 浏览器断开时，关闭Python流
            res.on('close', () => {
                pythonRes.data.destroy();
            });

        } catch (error) {
            res.write(
                `data: ${JSON.stringify({
                    type: 'error',
                    message: `无法连接到 Agent 服务: ${error.message}`,
                })}\n\n`,
            );
            res.end();
        }
    }

        /**
         * 流式数据扫描，并保存结果到数据库
         * @param sessionId Session ID
         * @param filePath 文件路径
         */
        streamDataScanWithMemory(sessionId: string, filePath: string): Observable<{ event?: string; data: any }> {
            if (!filePath) {
                throw new Error('File path is required');
            }

            return new Observable<{ event?: string; data: any }>((observer) => {
                let scanResult = '';
                let profileData: any = null;
                const tools: any[] = [];

                this.getDataScanStream(filePath, sessionId).subscribe({
                    next: (event) => {
                        observer.next(event);
                        const payload = event.data;
                                        
                        // 记录工具调用
                        if (payload?.tool && payload.type === 'tool_result') {
                            tools.push(payload);
                        }
                    
                        // 捕获完整的profile数据和累积扫描结果文本
                        if (payload?.type === 'final' && payload.profile) {
                            profileData = payload.profile;
                            scanResult += payload.message || '';
                            // 预存到 session 中
                            this.sessionModel.findByIdAndUpdate(sessionId, {
                                profile: profileData,
                                updatedAt: new Date(),
                            }).exec()
                                .then(() => this.logger.log('Data profile pre-saved to session'))
                                .catch(err => this.logger.error('Pre-save error:', err));
                        }
                    },
                    complete: async () => {
                        await this.persistDataScanResult(sessionId, scanResult, tools, profileData);
                        observer.complete();
                    },
                    error: async (err) => {
                        this.logger.error('Data scan stream interrupted:', err.message);
                        // 即使断开，也保存已获取的结果
                        await this.persistDataScanResult(sessionId, scanResult, tools, profileData);
                        observer.error(err);
                    },
                });
            });
        }

        /**
         * 获取数据扫描流
         * @param filePath 文件路径
         * @param sessionId Session ID
         */
        private getDataScanStream(filePath: string, sessionId?: string): Observable<{ event?: string; data: any }> {
            const agentApiUrl = `${process.env.agentUrl}/data-scan/stream`;
            const params = new URLSearchParams();
            params.append('file_path', filePath);
            if (sessionId) {
                params.append('session_id', sessionId);
            }

            return new Observable((observer) => {
                axios({
                    method: 'GET',
                    url: `${agentApiUrl}?${params.toString()}`,
                    responseType: 'stream',
                    headers: { Accept: 'text/event-stream' },
                }).then((response) => {
                    let buffer = '';

                    response.data.on('data', (chunk: Buffer) => {
                        buffer += chunk.toString();
                        const lines = buffer.split('\n');
                        buffer = lines.pop() || '';

                        for (const line of lines) {
                            if (line.startsWith('data: ')) {
                                try {
                                    const data = JSON.parse(line.substring(6));
                                    observer.next({ data });
                                } catch (e) {
                                    this.logger.warn(`Failed to parse SSE data: ${line}`);
                                }
                            }
                        }
                    });

                    response.data.on('end', () => {
                        observer.complete();
                    });

                    response.data.on('error', (err: any) => {
                        observer.error(err);
                    });
                }).catch((err) => {
                    observer.error(err);
                });
            });
        }

        /**
         * 保存数据扫描结果到数据库
         * @param sessionId Session ID
         * @param scanResult 扫描结果文本
         * @param tools 工具调用记录
         * @param profileData 数据 profile
         */
        private async persistDataScanResult(
            sessionId: string,
            scanResult: string,
            tools: any[],
            profileData: any
        ) {
            try {
                const tasks: Promise<any>[] = [];
            
                // 保存 AI 扫描工具消息
                if (scanResult || tools.length > 0) {
                    tasks.push(
                        this.saveMessage(
                            sessionId,
                            'AI',
                            scanResult || '',
                            tools.length ? tools : undefined,
                            'tool'
                        )
                    );
                }

                // 保存 AI 扫描结果消息
                if (scanResult || tools.length > 0) {
                    tasks.push(
                        this.saveMessage(
                            sessionId,
                            'AI',
                            scanResult || '',
                            tools.length ? tools : undefined,
                            'data',
                            profileData
                        )
                    );
                }
            
                // 保存 profile 数据到 session（兜底）
                if (profileData) {
                    tasks.push(
                        this.sessionModel.findByIdAndUpdate(sessionId, {
                            profile: profileData,
                            updatedAt: new Date(),
                        }).exec()
                    );
                }
            
                await Promise.all(tasks);
                this.logger.log(`Data scan results persisted for session ${sessionId}`);
            } catch (e) {
                this.logger.error('Failed to persist data scan results:', e);
            }
        }

        /**
         * 保存消息到数据库
         * @param sessionId Session ID
         * @param role 角色
         * @param content 内容
         * @param tools 工具调用
         */
        async saveMessage(
            sessionId: string,
            role: 'user' | 'AI' | 'system',
            content: string,
            tools?: any,
            type: 'text' | 'tool' | 'data' = 'text',
            profile?: any,
        ): Promise<Message> {
            const message = new this.messageModel({
                sessionId: new Types.ObjectId(sessionId),
                role,
                content,
                tools,
                type,
                profile,
            });

            const saved = await message.save();
            await this.sessionModel
                .findByIdAndUpdate(sessionId, {
                    $inc: { messageCount: 1 },
                    lastMessage: content.substring(0, 100),
                    updatedAt: new Date(),
                })
                .exec();

            return saved;
        }
    /**
     * 第四阶段：使用LLM检验、修正和补全数据分析结果
     * @param filePath 主要文件路径
     * @param initialResult 初步分析结果
     * @param pkg 数据包信息
     * @returns 修正和补全后的结果
     */
    private async refineProfileWithLLM(currentProfile: DataSemanticProfile, filePath: string): Promise<DataSemanticProfile> {
        const pythonApiUrl = `${process.env.agentUrl}/agents/data-refine`;

        try {
            this.logger.log(`请求 LLM 进行语义精炼... ID: ${currentProfile.id}`);

            // 构造请求体，匹配 Python 端 DataRefineRequest
            const payload = {
                file_path: filePath,
                profile: currentProfile, // 整个对象传过去
            };

            const response = await axios.post(pythonApiUrl, payload);
            const data = response.data;

            if (data.status === 'ok' && data.profile) {
                const refined = data.profile as DataSemanticProfile;
                
                // 记录 LLM 做了什么修正
                if (data.corrections?.length) {
                    this.logger.log(`[LLM 修正]: ${data.corrections.join('; ')}`);
                }
                if (data.completions?.length) {
                    this.logger.log(`[LLM 补全]: ${data.completions.join('; ')}`);
                }

                // 确保 ID 不被 LLM 篡改
                refined.id = currentProfile.id;
                return refined;
            } else {
                this.logger.warn(`LLM 返回状态非 OK: ${data.message}`);
                return currentProfile;
            }

        } catch (error) {
            // 容错处理：如果 LLM 服务挂了，返回原始 Profile，不要阻断上传流程
            this.logger.error(`LLM 精炼服务调用失败: ${error.message}`);
            return currentProfile;
        }
    }

    /**
     * 规范化参数类型
     * @param kernelType 原始类型字符串
     * @returns 规范化后的类型
     */
    private normalizeKernelType(kernelType?: string,): 'int' | 'float' | 'string' | 'boolean' {
        switch (kernelType?.toLowerCase()) {
            case 'int':
            case 'integer':
                return 'int';

            case 'float':
            case 'double':
            case 'number':
                return 'float';

            case 'bool':
            case 'boolean':
                return 'boolean';

            case 'string':
            default:
                return 'string';
        }
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
