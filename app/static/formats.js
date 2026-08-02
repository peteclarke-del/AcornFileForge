window.AcornFormats = (() => {
  const imageExtensions = [
    "ssd", "dsd", "mmb", "uef", "hfe",
    "ads", "adm", "adl", "adf",
    "dat", "hdf", "hdd", "img", "raw", "bin", "dsk"
  ];
  const imagePattern = new RegExp(`\\.(${imageExtensions.join("|")})$`, "i");
  const dfsPattern = /\.(ssd|dsd|hfe)$/i;
  const archivePattern = /\.zip$/i;
  const adfsPattern = /\.(ads|adm|adl|adf|dat|hdf|hdd|img|raw|bin|dsk|hfe|zip)$/i;

  return {
    accept: imageExtensions.map(extension => `.${extension}`).concat(".dsc", ".zip").join(","),
    isDescriptor: name => /\.dsc$/i.test(name),
    isArchive: name => archivePattern.test(name),
    isDfsImage: name => dfsPattern.test(name) || archivePattern.test(name),
    isImage: name => imagePattern.test(name),
    isImportableImage: name => imagePattern.test(name) || archivePattern.test(name),
    isPotentialAdfsImage: name => adfsPattern.test(name),
    stem: name => String(name).replace(/\.[^.]+$/, "")
  };
})();
