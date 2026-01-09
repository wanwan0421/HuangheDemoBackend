export interface TimeseriesProfile {
    time_step: {
        value: number
        unit: 'Second' | 'Minute' | 'Hour' | 'Day' | 'Month' | 'Year'
    }
    aggregation: 'Average' | 'Sum' | 'Min' | 'Max' | 'Count' | 'Instant'
}