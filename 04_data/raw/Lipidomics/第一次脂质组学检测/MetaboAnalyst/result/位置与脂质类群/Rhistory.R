# PID of current job: 360802
mSet<-InitDataObjects("conc", "msetqea", FALSE)
mSet<-Read.TextData(mSet, "Replacing_with_your_file_path", "rowu", "disc");
mSet<-SanityCheckData(mSet)
mSet<-ReplaceMin(mSet);
mSet<-CrossReferencing(mSet, "name", lipid = T);
mSet<-CreateMappingResultTable(mSet)
mSet<-PreparePrenormData(mSet)
mSet<-Normalization(mSet, "NULL", "NULL", "NULL", ratio=FALSE, ratioNum=20)
mSet<-PlotNormSummary(mSet, "norm_0_", "png", 72, width=NA)
mSet<-PlotSampleNormSummary(mSet, "snorm_0_", "png", 72, width=NA)
mSet<-SetMetabolomeFilter(mSet, F);
mSet<-SetCurrentMsetLib(mSet, "sub_class", 2);
mSet<-CalculateGlobalTestScore(mSet)
mSet<-PlotEnrichPieChart(mSet, "qea", "qea_pie_0_", "png", 72)
mSet<-PlotQEA.Overview(mSet, "qea_0_", "net", "png", 72, width=NA)
mSet<-PlotEnrichDotPlot(mSet, "qea", "qea_dot_0_", "png", 72, width=NA)
mSet<-SaveTransformedData(mSet)
mSet<-PreparePDFReport(mSet, "guest9894533315603268761")

mSet<-SetMetabolomeFilter(mSet, F);
mSet<-SetCurrentMsetLib(mSet, "main_class", 2);
mSet<-CalculateGlobalTestScore(mSet)
mSet<-PlotEnrichPieChart(mSet, "qea", "qea_pie_1_", "png", 72)
mSet<-PlotQEA.Overview(mSet, "qea_1_", "net", "png", 72, width=NA)
mSet<-PlotEnrichDotPlot(mSet, "qea", "qea_dot_1_", "png", 72, width=NA)
mSet<-SaveTransformedData(mSet)
mSet<-PreparePDFReport(mSet, "guest9894533315603268761")

mSet<-SetMetabolomeFilter(mSet, F);
mSet<-SetCurrentMsetLib(mSet, "super_class", 2);
mSet<-CalculateGlobalTestScore(mSet)
mSet<-PlotEnrichPieChart(mSet, "qea", "qea_pie_2_", "png", 72)
mSet<-PlotQEA.Overview(mSet, "qea_2_", "net", "png", 72, width=NA)
mSet<-PlotEnrichDotPlot(mSet, "qea", "qea_dot_2_", "png", 72, width=NA)
mSet<-SaveTransformedData(mSet)
mSet<-PreparePDFReport(mSet, "guest9894533315603268761")

mSet<-PreparePDFReport(mSet, "guest9894533315603268761")

mSet<-SaveTransformedData(mSet)
mSet<-PreparePDFReport(mSet, "guest9894533315603268761")

mSet<-SetMetabolomeFilter(mSet, F);
mSet<-SetCurrentMsetLib(mSet, "predicted", 2);
mSet<-CalculateGlobalTestScore(mSet)
mSet<-SetMetabolomeFilter(mSet, F);
mSet<-SetCurrentMsetLib(mSet, "location", 2);
mSet<-CalculateGlobalTestScore(mSet)
mSet<-PlotQEA.Overview(mSet, "qea_3_", "net", "png", 72, width=NA)
mSet<-PlotEnrichDotPlot(mSet, "qea", "qea_dot_3_", "png", 72, width=NA)
mSet<-SaveTransformedData(mSet)
