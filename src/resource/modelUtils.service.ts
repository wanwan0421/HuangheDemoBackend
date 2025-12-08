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
            const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '' }); // 不忽略属性并去掉属性名前缀
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
                    keywords: LocalAttribute.Keywords?.text ?? "",
                    abstract: LocalAttribute.Abstract?.text ?? ""
                };

                if (LocalAttribute.local === 'EN_US') {
                    mdlObject.enAttr = obj;
                } else if (LocalAttribute.local === 'ZH_CN') {
                    mdlObject.cnAttr = obj;
                }
            }

            // 读取相关数据
            let RelatedDarasets = Behavior.RelatedDarasets;
            if (!RelatedDarasets) {
                RelatedDarasets = Behavior.DatasetDeclarations;
            }

            const DatasetItems = RelatedDarasets.DatasetItem;
            const items = Array.isArray(DatasetItems) ? DatasetItems : [DatasetItems];
            const DatasetItemArray: any[] = [];

            for (const item of items) {
                const datasetArray: any[] = [];

                // 根节点
                const root: any = {
                    text: item.name,
                    dataType: item.type,
                    description: item.description
                };

                if (item.type === "external") {
                    root.externalId = item.externalId?.toLowerCase() || item.EXTERNAL?.toLowerCase() || "";
                    root.parentId = "null";
                    datasetArray.push(root);
                } else {
                    const Udx = item.UdxDeclaration || item.UDXDeclaration;

                    const rootId = Udx.id ? "root" + Udx.id : "root" + crypto.randomUUID();
                    root.Id = rootId;
                    root.parentId = "null";

                    const udxNode = Udx.UDXNode || Udx.UdxNode;
                    const udxChildren = Array.isArray(udxNode?.UDXNode)
                        ? udxNode.UDXNode
                        : udxNode
                            ? [udxNode]
                            : [];

                    root.schema = this.extractUdxSchema(mdlXml, root.text);
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
                    name: state.name,
                    type: state.type,
                    desc: state.description,
                    Id: state.id,
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
                        // 在 DataItems 中查找对应 datasetReference
                        for (const ds of mdlObject.DataItems) {
                            const rootItem = ds[0];
                            if (rootItem.text === Parameter.datasetReference) {
                                evObj.data = ds;
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

        for (const udxNode of udxNodes) {
            const node: any = {};

            // name -> text
            node.text = udxNode.attributes?.name || "";

            // 类型解析逻辑
            const dataType = udxNode.attributes?.type || "";
            let dataTypeResult = "";

            const dataTypes = dataType.split("|");

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
                const parts = dataType.split("_");
                dataTypeResult = parts[1] || "";
            }

            node.dataType = dataTypeResult;

            // desc
            node.desc = udxNode.attributes?.description || "";

            // external 属性
            if (dataType === "external") {
                node.externalId = (udxNode.attributes?.externalId || "").toLowerCase();
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