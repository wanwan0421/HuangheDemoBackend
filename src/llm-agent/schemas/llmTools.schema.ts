import { Type } from '@google/genai';

export const indexRecommendationTool = {
    name: 'recommend_index',
    description: 'Recommend the top 5 most suitable indexes from the the provided context.',
    parameters: {
        type: Type.OBJECT,
        properties: {
            recommendations: {
                type: Type.ARRAY,
                items: {
                    type: Type.OBJECT,
                    properties: {
                        name: {
                            type: Type.STRING,
                            description: 'Index name (e.g., "Terrain Relief", "Total Solar Radiation")'
                        },
                        reason: {
                            type: Type.STRING,
                            description: 'Explain why this index matches the user requirement.'
                        }
                    },
                    required: ['name', 'reason'],
                },
                description: 'A list of 5 recommended indexs',
            }
        },
        required: ['recommendations'],
    },
};

export const modelRecommendationTool = {
    name: 'recommend_model',
    description: 'Recommend the most suitable geographic computing model from the provided model information.',
    parameters: {
        type: Type.OBJECT,
        properties: {
            md5: {
                type: Type.STRING,
                description: 'The md5 of the most matching geographical model recommended by the system (e.g., "00ac830b4da73eab8d482b2f11b537db")'
            },
            reason: {
                type: Type.STRING,
                description: 'Explain why the system recommends the best matching geographic model.'
            }
        },
        required: ['md5', 'reason'],
    },
};