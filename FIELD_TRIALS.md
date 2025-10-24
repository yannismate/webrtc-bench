# Newly Added FieldTrials

## Starlink Optimization

### StarlinkReconfigurationGuard
- **Type**: Boolean
- **Format**: Enabled/Disabled flag
- **Purpose**: Enables Starlink reconfiguration guard mechanism as alternative approach

### StarlinkIntervalDetection
- **Type**: Boolean
- **Format**: Enabled/Disabled flag
- **Purpose**: Enables interval-based reconfiguration detection for Starlink

### StarlinkGuardProbing
- **Type**: Boolean
- **Format**: Enabled/Disabled flag
- **Purpose**: Enables probing after Starlink reconfiguration detection

### StarlinkGuardProbingMaxKbps
- **Type**: Integer
- **Format**: Positive integer in kbps, e.g., "5000"
- **Purpose**: Sets maximum data rate below which probing will be triggered after reconfiguration

### StarlinkGuardProbingValues
- **Type**: String
- **Format**: Dash-separated integer percentages, e.g., "50-125-150"
- **Purpose**: Defines custom probing multiplier values for Starlink guard

### StarlinkGuardProbingAllowFurther
- **Type**: Boolean
- **Format**: Enabled/Disabled flag
- **Purpose**: Allows further exponential probing after reconfiguration probes are triggered

### StarlinkGuardSelfFIR
- **Type**: Boolean
- **Format**: Enabled/Disabled flag
- **Purpose**: Enables self-FIR functionality for Starlink guard


## FEC Configuration

### BurstFecEnabled
- **Type**: Boolean
- **Format**: Enabled/Disabled flag
- **Purpose**: Enables burst FEC mask type instead of random FEC

### BurstFecStaticOverhead
- **Type**: Float
- **Format**: Percentage value between (0, 50], e.g., "25" for 25%
- **Purpose**: Sets a static FEC overhead rate instead of dynamic calculation