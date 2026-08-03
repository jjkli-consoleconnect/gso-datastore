  /**
  * Main entry point - creates custom menu on spreadsheet open
  */
  function onOpen() {
    createCustomMenus();
  }

  /**
  * Creates custom menus in the spreadsheet UI
  */
  function createCustomMenus() {
    const ui = SpreadsheetApp.getUi();

    const reviewQueueEnabled = !!(CONFIG && CONFIG.FEATURES && CONFIG.FEATURES.REVIEW_QUEUE_ENABLED);

    // Operations menu
    const operationsMenu = ui.createMenu('Operations')
      .addItem('Load Emails', 'loadEmailDetails');

    if (reviewQueueEnabled) {
      operationsMenu
        .addSeparator()
        .addItem('Refresh Review Queue', 'refreshReviewQueue');
    }

    operationsMenu.addToUi();

    // Setup menu: keep audit tools available even without Review Queue.
    const setupMenu = ui.createMenu('Setup')
      .addItem('Install Audit', 'installAuditTrigger')
      .addItem('Remove Audit', 'removeAuditTrigger')
      .addSeparator()
      .addItem('Install ReviewStatus Dropdowns', 'installReviewStatusDropdowns')
      .addItem('Remove ReviewStatus Trigger', 'removeReviewStatusTrigger')
      .addSeparator()
      .addItem('Install Invalid Date/Time Highlighting', 'installInvalidDateTimeHighlighting');

    if (reviewQueueEnabled) {
      setupMenu
        .addSeparator()
        .addItem('Migrate Status', 'migrateReviewStatusColumn');
    }
    setupMenu.addToUi();

    const devMenu = ui.createMenu('Dev Tools')
      .addItem('Check Audit Setup', 'checkAuditSetup')
      .addItem('Check Audit Buffer', 'checkAuditBuffer')
      .addItem('Clear Audit Buffer', 'clearAuditBuffer')
      .addItem('Test Audit Flush', 'testAuditFlush');

    devMenu
      .addSeparator()
      .addItem('Generate OutageID (selection)', 'devGenerateOutageIdForSelection');

    devMenu
      .addItem('Recompute OutageID (selection, overwrite)', 'devRecomputeOutageIdForSelection');

    devMenu
      .addItem('Generate OutageID (all sheets)', 'devGenerateOutageIdForAllSheets');

    devMenu.addToUi();

    // Consolidation menu (existing sheet workflow)
    ui.createMenu('BQ Sync')
      .addItem('Sync to BQ-consolidated', 'consolidateAllSimple')
      .addToUi();
  }

