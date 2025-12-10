import { XMLParser } from 'fast-xml-parser';
import { MdlEventParameter } from './interfaces/portalSync.interface';
import { Injectable } from '@nestjs/common';

@Injectable()
export class ModelUtilsService {
    // 将MDL的XML字符串转换为JSON对象
    // @param mdlXml 原始MDL的XML字符串
    // @param mdlJson 转换后的JSON对象
    public async convertMdlXmlToJson(mdlXml: string): Promise<Record<string, any>> {
        let xmlObject: any;
        try {
            const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '', textNodeName: 'text' }); // 不忽略属性并去掉属性名前缀, 保留文本节点名称为 'text'
            xmlObject = parser.parse(mdlXml); // 将XML字符串解析为JS对象

            const rootKey = Object.keys(xmlObject)[0]; // 获取根节点，对应MDL中的ModelClass
            const rootElement = xmlObject[rootKey];

            const mdlObject: any = {};

            // 读取根节点属性
            mdlObject.name = rootElement.name || '';

            // 读取AttributeSet和Behavior属性
            const AttributeSet = rootElement.AttributeSet || {};
            const Behavior = rootElement.Behavior || {};
            if (!AttributeSet || !Behavior) {
                throw new Error('Invalid MDL structure: Missing AttributeSet or Behavior');
            }

            // 读取基本属性
            const Categories = AttributeSet.Categories || {};
            if (!Categories) {
                throw new Error('Invalid MDL structure: Missing Categories');
            }

            mdlObject.principle = Categories.Category?.principle || '';
            mdlObject.path = Categories.Category?.path || '';

            const LocalAttributes = AttributeSet?.LocalAttributes?.LocalAttribute;

            if (!LocalAttributes) {
                throw new Error('Invalid MDL structure: Missing LocalAttributes');
            }

            const locals = Array.isArray(LocalAttributes) ? LocalAttributes : [LocalAttributes];
            for (const LocalAttribute of locals) {
                const obj = {
                    localName: LocalAttribute.localName,
                    keywords: LocalAttribute.Keywords,
                    abstract: LocalAttribute.Abstract
                };

                if (LocalAttribute.local === 'EN_US') {
                    mdlObject.enAttr = obj;
                } else if (LocalAttribute.local === 'ZH_CN') {
                    mdlObject.cnAttr = obj;
                }
            }

            // 读取相关数据
            let RelatedDatasets = Behavior.RelatedDatasets;
            if (!RelatedDatasets) {
                RelatedDatasets = Behavior.DatasetDeclarations;
            }

            const DatasetItems = RelatedDatasets.DatasetItem;
            const items = Array.isArray(DatasetItems) ? DatasetItems : [DatasetItems];
            const DatasetItemArray: any[] = [];

            for (const item of items) {
                const datasetArray: any[] = [];

                // 根节点
                const root: any = {
                    name: item.name,
                    type: item.type,
                    description: item.description
                };

                if (item.type === "external") {
                    root.externalId = item.externalId?.toLowerCase() || item.EXTERNAL?.toLowerCase() || "";
                    root.parentId = "null";
                    datasetArray.push(root);
                } else {
                    const Udx = item.UdxDeclaration || item.UDXDeclaration;

                    const rootId = Udx.id ? "root" + Udx.id : "root" + crypto.randomUUID();
                    root.internalId = rootId;
                    root.parentId = "null";

                    let udxNode = Udx.UDXNode || Udx.UdxNode;

                    // 先检查Udx.UDXNode是否是一个包裹对象，里面又嵌套了UDXNode属性
                    if (udxNode && !Array.isArray(udxNode) && (udxNode.UDXNode || udxNode.UdxNode)) {
                        udxNode = udxNode.UDXNode || udxNode.UdxNode;
                    }

                    const udxChildren = Array.isArray(udxNode)
                        ? udxNode
                        : udxNode ? [udxNode] : [];

                    root.schema = this.extractUdxSchema(mdlXml, root.name);
                    root.nodes = [];

                    // 递归解析UDX树
                    this.parseUdxNodes(udxChildren, root);

                    datasetArray.push(root);
                }

                DatasetItemArray.push(...datasetArray);
            }

            mdlObject.DatasetItems = DatasetItemArray;

            // 读取状态/事件（State/Event）
            const States = Behavior?.StateGroup?.States;
            const stateList = Array.isArray(States?.State) ? States.State : [States.State];

            const statesArr: any[] = [];

            for (const state of stateList) {
                const stateObj: any = {
                    stateName: state.name,
                    stateType: state.type,
                    stateDesc: state.description,
                    stateId: state.id,
                    event: []
                };

                const events = Array.isArray(state.Event)
                    ? state.Event
                    : [state.Event];

                for (const ev of events) {
                    const evObj: any = {
                        eventId: crypto.randomUUID(),
                        eventName: ev.name,
                        eventType: ev.type,
                        eventDesc: ev.description,
                    };

                    // optional / multiple
                    if (ev.optional) {
                        evObj.optional = ev.optional.toLowerCase() === "true";
                    }
                    if (ev.multiple) {
                        evObj.multiple = ev.multiple.toLowerCase() === "true";
                    }

                    // 参数节点 DispatchParameter / ResponseParameter / ControlParameter
                    let Parameter: MdlEventParameter | null = null;

                    if (ev.type === "response") {
                        Parameter = ev.ResponseParameter || ev.ControlParameter;
                    } else {
                        Parameter = ev.DispatchParameter || ev.ControlParameter;
                    }

                    if (Parameter?.datasetReference) {
                        // 在 DatasetItems 中查找对应 datasetReference
                        for (const ds of mdlObject.DatasetItems) {
                            if (!ds || ds.length === 0) {
                                console.log('DatasetItems entry is empty or undefined');
                                continue;
                            }
                            // const rootItem = ds[0];
                            if (ds.name === Parameter.datasetReference) {
                                evObj.data = [ds]; // 将找到的 DatasetItem 根对象赋值给 evObj.data
                                break; // 找到后退出循环以提高效率
                            }
                        }
                    }

                    stateObj.event.push(evObj);
                }

                statesArr.push(stateObj);
            }
            mdlObject.states = statesArr;
            return { mdl: mdlObject };

        } catch (error) {
            throw new Error(`Error parsing MDL XML: ${error}`);
        }
    }

    // 递归解析UDX节点
    public extractUdxSchema(text: string, name: string): string {
        const findIndex = text.indexOf(name);
        if (findIndex === -1) return "";

        const startIndex = text.indexOf(">", findIndex + name.length) + 1;
        const endIndex = text.indexOf("</DatasetItem>", startIndex);

        if (startIndex === -1 || endIndex === -1) return "";

        return text.substring(startIndex, endIndex);
    }

    // 解析UDX树
    public parseUdxNodes(udxNodes: any[], root: any) {
        if (!udxNodes || udxNodes.length === 0) return;

        for (const rawUdxNode of udxNodes) {
            const udxNode = rawUdxNode?.UdxNode || rawUdxNode;
            const node: any = {};

            // name -> text
            node.name = udxNode?.name || "";

            // 类型解析逻辑
            const type = udxNode?.type || "";
            let dataTypeResult = "";

            const dataTypes = type.split("|");

            if (dataTypes.length > 1) {
                dataTypes.forEach((dt, index) => {
                    const parts = dt.trim().split("_");
                    if (parts[1] === "LIST") {
                        parts[1] = "ARRAY";
                    }
                    dataTypeResult += parts[1];

                    if (index !== dataTypes.length - 1) {
                        dataTypeResult += "_";
                    }
                });
            } else {
                const parts = type.split("_");
                dataTypeResult = parts[1] || "";
            }

            node.dataType = dataTypeResult;

            // description
            node.description = udxNode?.description || "";

            // external 属性
            if (type === "external") {
                node.externalId = (udxNode?.externalId || "").toLowerCase();
            }

            // 子节点
            const children = udxNode.elements || [];
            if (children.length > 0) {
                node.nodes = [];
                this.parseUdxNodes(children, node);
            }

            // push 到 root.nodes
            if (!root.nodes) root.nodes = [];
            root.nodes.push(node);
        }
    }
}