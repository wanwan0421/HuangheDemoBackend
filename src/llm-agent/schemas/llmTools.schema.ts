import { Type } from '@google/genai';

export const indexRecommendationTool = {
    name: 'recommend_index',
    description: 'Recommend the top 5 most suitable geographic computing modela from the the provided context.',
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
                            description: 'Model name (e.g., "UrbanM2M", "SWAT_Model")'
                        },
                        reason: {
                            type: Type.STRING,
                            description: 'Explain why this model matches the user requirement.'
                        }
                    },
                    required: ['name', 'reason'],
                },
                description: 'A list of 3 recommended models',
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
            name: {
                type: Type.STRING,
                description: 'The name of the most matching geographical model recommended by the system (e.g., "UrbanM2M", "SWAT_Model")'
            },
            reason: {
                type: Type.STRING,
                description: 'Explain why the system recommends the best matching geographic model.'
            }
        },
        required: ['name', 'reason'],
    },
};