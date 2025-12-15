import { Type } from '@google/genai';

export const modelRecommendationTool = {
    name: 'recommend_model',
    description: 'Recommend the most suitable geographic computing model from the model base according to the geographic decision requirements input by users.',
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