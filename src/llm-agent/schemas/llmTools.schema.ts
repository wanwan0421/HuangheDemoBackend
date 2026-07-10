export const indexRecommendationTool = {
    name: 'recommend_index',
    description: 'Recommend the top 5 most suitable indexes from the the provided context.',
    parameters: {
        type: 'object',
        properties: {
            recommendations: {
                type: 'array',
                items: {
                    type: 'object',
                    properties: {
                        name: {
                            type: 'string',
                            description: 'Index name (e.g., "Terrain Relief", "Total Solar Radiation")'
                        },
                        reason: {
                            type: 'string',
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
        type: 'object',
        properties: {
            md5: {
                type: 'string',
                description: 'The md5 of the most matching geographical model recommended by the system (e.g., "00ac830b4da73eab8d482b2f11b537db")'
            },
            reason: {
                type: 'string',
                description: 'Explain why the system recommends the best matching geographic model.'
            }
        },
        required: ['md5', 'reason'],
    },
};
